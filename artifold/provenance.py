"""Persistent per-artifact metadata, keyed by content hash.

Keyed by SHA1(content) so a file moving / being renamed doesn't lose its
source / prompt / tags / model. The store lives in the cache dir:
`<cache>/provenance.json`. Schema is versioned for future migrations.

Each entry shape:
    {
      "source":   "https://claude.ai/share/...",  // chat or artifact URL
      "tool":     "claude" | "chatgpt" | "v0" | "lovable" | "bolt" | "gemini"
                  | "manual" | null,
      "model":    "claude-opus-4-7" | null,
      "prompt":   "<the prompt that made it>" | null,
      "tags":     [],
      "notes":    "",
      "added_at": "<iso>"
    }
"""
from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .paths import CACHE_DIR, ensure_dirs

SCHEMA = 1
STORE = CACHE_DIR / "provenance.json"

VALID_TOOLS = {"claude", "chatgpt", "v0", "lovable", "bolt", "gemini",
               "cursor", "manual", None}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha1_of(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# Parsed-store memo, keyed on the file's identity. One scan of a 133-project
# library called _load_raw 670 times; at a 546 KB store that is ~366 MB of
# JSON parsed to answer per-file lookups. The key is (mtime_ns, size) so an
# edit by another process still invalidates it.
_CACHE: tuple[tuple[str, int, int], dict] | None = None


def _store_key() -> tuple[str, int, int] | None:
    """(path, mtime_ns, size). The path is part of the key because STORE is
    reassignable — tests point it at a temp file, and two stores must never
    share a cache entry."""
    try:
        st = STORE.stat()
    except OSError:
        return None
    return (str(STORE), st.st_mtime_ns, st.st_size)


def _load_raw() -> dict:
    global _CACHE
    # Inside a batch the memo is the only copy of pending writes — the file
    # on disk is deliberately behind. Trust it, including on a first-ever
    # scan where the store does not exist yet and `_store_key()` is None.
    if _batch_depth > 0 and _CACHE is not None:
        return _CACHE[1]
    key = _store_key()
    if key is None:
        return {"version": SCHEMA, "items": {}}
    if _CACHE is not None and _CACHE[0] == key:
        return _CACHE[1]
    try:
        d = json.loads(STORE.read_text())
    except Exception:
        return {"version": SCHEMA, "items": {}}
    if d.get("version") != SCHEMA:
        # future migrations land here
        d.setdefault("items", {})
        d["version"] = SCHEMA
    _CACHE = (key, d)
    return d


# Deferred-write state. A scan enriches every file, and each enrichment used
# to re-serialise the whole store: 273 writes of a 546 KB document in one
# scan, which profiled at 75% of total scan time. Inside a batch, writes
# accumulate in memory and land once at the end.
_batch_depth = 0
_batch_dirty = False


def _write_now(d: dict) -> None:
    global _CACHE
    ensure_dirs()
    STORE.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    key = _store_key()
    _CACHE = (key, d) if key else None


def _save_raw(d: dict) -> None:
    global _CACHE, _batch_dirty
    if _batch_depth > 0:
        # Keep the memo authoritative so reads inside the batch see the
        # mutation, and defer the expensive serialise to the flush.
        _CACHE = (_CACHE[0] if _CACHE else _store_key(), d)
        _batch_dirty = True
        return
    _write_now(d)


@contextmanager
def batch():
    """Collect provenance writes and flush once on exit.

    Safe to lose: everything written during a scan is derived from files on
    disk, so a crash mid-batch costs one scan's enrichment and the next scan
    rebuilds it. `carry_forward` is self-healing the same way — an unwritten
    link leaves the old entry un-superseded, and the next scan redoes it.

    Re-entrant, so a caller can wrap a region without knowing whether an
    outer batch is already open.
    """
    global _batch_depth, _batch_dirty
    _batch_depth += 1
    try:
        yield
    finally:
        _batch_depth -= 1
        if _batch_depth == 0 and _batch_dirty:
            _batch_dirty = False
            if _CACHE is not None:
                _write_now(_CACHE[1])


def get(sha: str) -> dict | None:
    return _load_raw()["items"].get(sha)


def set_(sha: str, **fields) -> dict:
    """Upsert provenance fields for a content hash. Unknown keys are kept."""
    d = _load_raw()
    cur = d["items"].setdefault(sha, {"added_at": _now()})
    if "tool" in fields and fields["tool"] not in VALID_TOOLS:
        raise ValueError(f"tool must be one of {sorted(t for t in VALID_TOOLS if t)}")
    for k, v in fields.items():
        if v is None:
            continue
        if k == "tags" and isinstance(v, list):
            cur["tags"] = sorted(set((cur.get("tags") or []) + v))
        else:
            cur[k] = v
    _save_raw(d)
    return cur


def annotate_path(path: Path, **fields) -> tuple[str, dict]:
    """Convenience: compute hash for a path, then set_(). Returns (sha, entry)."""
    sha = sha1_of(path)
    entry = set_(sha, **fields)
    return sha, entry


def all_items() -> dict[str, dict]:
    return dict(_load_raw()["items"])


def carry_forward(new_sha: str, path: Path) -> dict | None:
    """A file was edited in place: its content hash changed, so the old
    entry no longer matches. Copy the old entry (found by `path`, recorded
    at scan time) onto the new hash so source/prompt/tags/shares survive
    edits, not just moves. The old entry is marked superseded (GC'd later,
    so a Trash-restore of the old content still reattaches within the TTL).
    Returns the new entry, or None if there was nothing to carry."""
    d = _load_raw()
    items = d["items"]
    if new_sha in items:
        return items[new_sha]
    p = str(path)
    old_sha = next((s for s, e in items.items()
                    if e.get("path") == p and not e.get("superseded_by")), None)
    if not old_sha:
        return None
    fresh = dict(items[old_sha])
    fresh.pop("superseded_by", None)
    fresh.pop("orphaned_at", None)
    # The fingerprint describes the *old* bytes. Carrying it forward onto a
    # new hash would hand the next scan a cache entry that looks current and
    # is not — the file's palette and fonts would silently stay stale until
    # the entry was evicted. Everything else here (source, prompt, tags,
    # shares, open counts) is about the artifact, not its bytes, and stays.
    fresh.pop("design", None)
    fresh["previous_sha"] = old_sha
    # Stamp both ends of the link. `added_at` stays the original creation
    # time — the artifact was made then, not re-made — so without these two
    # stamps the whole chain claims one timestamp and the history has no
    # time in it. Chains built before v0.9 stay time-blind; their length is
    # still accurate.
    now = _now()
    fresh["revised_at"] = now
    items[new_sha] = fresh
    items[old_sha]["superseded_by"] = new_sha
    items[old_sha]["superseded_at"] = now
    _save_raw(d)
    return fresh


def chain_for(sha: str) -> list[dict]:
    """The edit history of one artifact, oldest revision first.

    Walks `previous_sha` back through the superseded entries. Each element
    is {sha, revised_at, superseded_at, added_at}. The live entry is last.

    Only records that the content changed and when. The store keeps hashes,
    not bytes, so the old content is gone and these cannot be diffed.
    """
    items = _load_raw()["items"]
    out: list[dict] = []
    seen: set[str] = set()
    cur: str | None = sha
    while cur and cur in items and cur not in seen:
        seen.add(cur)
        e = items[cur]
        out.append({
            "sha1": cur,
            "added_at": e.get("added_at"),
            "revised_at": e.get("revised_at"),
            "superseded_at": e.get("superseded_at"),
        })
        cur = e.get("previous_sha")
    out.reverse()
    return out


def record_open(sha: str) -> dict | None:
    """Count a deliberate open of an artifact.

    Creation time says when the user made something. It never says what the
    user comes back to, and at 130+ artifacts those are different questions.
    Previewing a card does not count; only an explicit open does.
    """
    d = _load_raw()
    e = d["items"].get(sha)
    if e is None:
        return None
    e["open_count"] = int(e.get("open_count") or 0) + 1
    e["last_opened_at"] = _now()
    _save_raw(d)
    return e


def sha_for_path(path: str | Path) -> str | None:
    """Find the live entry recorded at `path`. Lets the server count an open
    from the path the dashboard already has, without re-hashing the file.

    Compares resolved paths: the store writes the path seen during the walk,
    while the server resolves symlinks first, so a raw string match misses
    whenever a root is a symlink (/tmp on macOS, for one).
    """
    want = Path(path)
    try:
        want = want.resolve()
    except OSError:
        pass
    for sha, e in _load_raw()["items"].items():
        if e.get("superseded_by") or e.get("orphaned_at"):
            continue
        raw = e.get("path")
        if not raw:
            continue
        if raw == str(path):
            return sha
        try:
            if Path(raw).resolve() == want:
                return sha
        except OSError:
            continue
    return None


ORPHAN_TTL_DAYS = 30
# Revisions kept per artifact. Chains are a few small JSON objects each, so
# this only exists to bound a pathological case; the longest real chain
# observed in three months of use is 28.
MAX_CHAIN = 50


def _chain_ancestors(items: dict, heads: set[str]) -> set[str]:
    """Every superseded revision reachable from a live artifact.

    A superseded entry's content hash is gone from disk by definition, so
    the plain orphan rule stamps all of them and deletes them 30 days on.
    That put the whole edit history on a timer: it was being collected
    before anything could show it. Ancestors of a live head are history,
    not litter, and are kept for as long as the head lives.
    """
    keep: set[str] = set()
    for head in heads:
        cur, hops = items.get(head, {}).get("previous_sha"), 0
        while cur and cur in items and cur not in keep and hops < MAX_CHAIN:
            keep.add(cur)
            cur = items[cur].get("previous_sha")
            hops += 1
    return keep


def gc(active_shas: set[str]) -> int:
    """Reconcile the store against a full scan. Entries whose hash wasn't
    seen get stamped `orphaned_at` (and dropped after ORPHAN_TTL_DAYS);
    entries seen again get the stamp cleared (Trash restore, git checkout).
    Revisions of a live artifact are exempt — see `_chain_ancestors`.
    Returns the number of entries deleted."""
    d = _load_raw()
    items = d["items"]
    now = datetime.now(timezone.utc)
    history = _chain_ancestors(items, active_shas)
    deleted = 0
    for sha in list(items):
        e = items[sha]
        if sha in active_shas or sha in history:
            e.pop("orphaned_at", None)   # re-seen, or part of a live history
            continue
        # A share is a fact about a URL that is live on the public internet.
        # It is not a fact about a byte sequence, so it must not die with one.
        # Losing it silently is the worst outcome here: the artifact stays
        # published and the library stops being able to say so. (This is how
        # 11 real shares went missing — the entries that held them were
        # superseded by an edit, orphaned, and TTL'd out.)
        if e.get("shares"):
            e.pop("orphaned_at", None)
            continue
        # Not in the scan, but its file still exists and no newer content
        # took over the path (variants, depth-excluded or hand-linked
        # files land here). Leave them alone.
        p = e.get("path")
        if p and not e.get("superseded_by") and Path(p).is_file():
            e.pop("orphaned_at", None)
            continue
        stamp = e.get("orphaned_at")
        if not stamp:
            e["orphaned_at"] = now.isoformat(timespec="seconds")
            continue
        try:
            age = now - datetime.fromisoformat(stamp)
        except ValueError:
            e["orphaned_at"] = now.isoformat(timespec="seconds")
            continue
        if age.days >= ORPHAN_TTL_DAYS:
            del items[sha]
            deleted += 1
    _save_raw(d)
    return deleted
