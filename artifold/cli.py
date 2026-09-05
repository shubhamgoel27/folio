"""Artifold CLI.

Subcommands:
    artifold init                    create config dir
    artifold add <dir>               add a root to scan
    artifold remove <dir>            remove a root
    artifold roots                   list configured roots
    artifold scan                    scan + screenshot + build (one-shot)
    artifold serve [--port N]        live dashboard with auto-rescan
    artifold open                    print the dashboard URL / file
    artifold                         default: serve + open the browser
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import webbrowser
from pathlib import Path

from . import __version__, config, provenance
from .paths import CONFIG_DIR, CONFIG_FILE, INDEX, ensure_dirs


def _count_html(p: Path, max_count: int = 9999) -> int:
    n = 0
    try:
        for _ in p.rglob("*.html"):
            n += 1
            if n >= max_count:
                break
    except Exception:
        pass
    return n


def _is_tty() -> bool:
    import sys
    return sys.stdin.isatty() and sys.stdout.isatty()


def _cmd_init(args):
    ensure_dirs()
    if not CONFIG_FILE.exists():
        config.save(dict(config.DEFAULTS))

    print(f"\n  📚  Artifold — local library for your AI-generated artifacts\n")
    print(f"  config: {CONFIG_FILE}\n")

    if args.non_interactive or not _is_tty():
        print("  (non-interactive — skipping wizard. next: `artifold add <dir>`)")
        return 0

    cfg = config.load()
    existing = cfg.get("roots") or []
    if existing:
        print(f"  Already configured roots:")
        for r in existing:
            print(f"    · {r}")
        print()
        ans = input("  Add another? [y/N]: ").strip().lower()
        if ans in ("y", "yes"):
            _wizard_pick_root(existing)
    else:
        _wizard_pick_root(existing)

    cfg = config.load()
    if not (cfg.get("roots") or []):
        print("\n  Nothing scanned yet. Add a root any time: artifold add <dir>")
        return 0

    ans = input("\n  Run an initial scan now? (~30s + chromium download on first run) [Y/n]: ").strip().lower()
    if ans in ("n", "no"):
        print("  ok — run `artifold scan` when ready.")
        return 0

    from . import scan, shoot, build
    import asyncio
    rs = config.roots()
    print()
    projects = scan.scan_all()
    print(f"  found {len(projects)} project(s) "
          f"({sum(p['file_count'] for p in projects)} html files)")
    asyncio.run(shoot.shoot(projects))
    build.build(projects, [str(r) for r in rs])

    if input("\n  Open the dashboard? [Y/n]: ").strip().lower() not in ("n", "no"):
        return _cmd_open(None)
    print("\n  done. run `artifold` any time to view + auto-rescan.")
    return 0


def _wizard_pick_root(existing: list[str]):
    existing_set = {str(Path(r).expanduser().resolve()) for r in existing}
    candidates = [Path.home() / d for d in ("Downloads", "Documents", "Desktop")]
    candidates = [c for c in candidates
                  if c.is_dir() and str(c) not in existing_set]
    if candidates:
        print("\n  Common places AI-generated HTML lands:")
        for i, c in enumerate(candidates, 1):
            n = _count_html(c, 200)
            note = f"~{n} html files" if n < 200 else "200+ html files"
            print(f"    {i}. {c}   ({note})")
        print(f"    {len(candidates)+1}. enter a custom path")
        print(f"    {len(candidates)+2}. skip — add later")
        choice = input(f"\n  Pick [1-{len(candidates)+2}]: ").strip()
        if not choice.isdigit():
            return
        idx = int(choice) - 1
        if 0 <= idx < len(candidates):
            ok, msg = config.add_root(candidates[idx])
            print(f"    {'added' if ok else '!'} {msg}")
            return
        if idx == len(candidates):
            _wizard_custom_path()
        return
    _wizard_custom_path()


def _wizard_custom_path():
    p = input("  Path to scan: ").strip()
    if not p:
        return
    ok, msg = config.add_root(p)
    print(f"    {'added' if ok else '!'} {msg}")


def _cmd_add(args):
    ok, msg = config.add_root(args.path)
    print(("added: " if ok else "! ") + msg)
    return 0 if ok else 1


def _cmd_remove(args):
    ok, msg = config.remove_root(args.path)
    print(("removed: " if ok else "! ") + msg)
    return 0 if ok else 1


def _cmd_roots(_args):
    rs = config.load().get("roots") or []
    if not rs:
        print("(no roots configured)  run: artifold add <dir>")
        return
    for r in rs:
        print(r)


def _cmd_allow_repo(args):
    """Add or list dir names with their own .git that should be scanned anyway.
    Default behavior is to skip these (most are cloned source code)."""
    if not args.name:
        allow = config.allow_repos()
        if not allow:
            print("(no repos allow-listed; git-repo subdirs are excluded by default)")
        else:
            for n in allow:
                print(n)
        return 0
    ok, msg = config.add_allow_repo(args.name)
    print(("allow-listed: " if ok else "! ") + msg)
    return 0 if ok else 1


def _cmd_disallow_repo(args):
    ok, msg = config.remove_allow_repo(args.name)
    print(("removed from allow-list: " if ok else "! ") + msg)
    return 0 if ok else 1


def _cmd_scan(args):
    from . import scan, shoot, build
    rs = config.roots()
    if not rs:
        print("! no roots configured. run: artifold add <dir>")
        return 1
    intent_override = True if args.intent else (False if args.no_intent else None)
    if args.intent:                       # explicit opt-in: explain if we'll skip
        from . import intent as _intent
        try:
            import anthropic  # noqa: F401
        except ImportError:
            print("  ! --intent: extra not installed. run: pip install 'artifold[intent]'")
            intent_override = False
        else:
            if not _intent.have_api_key():
                print("  ! --intent: ANTHROPIC_API_KEY not set; intent will be skipped")
                intent_override = False
    print(f"scanning {len(rs)} root(s)…")
    projects = scan.scan_all(intent_override=intent_override)
    print(f"  found {len(projects)} projects "
          f"({sum(p['file_count'] for p in projects)} html files)")
    if args.no_shoot:
        cached = shoot.resolve_cached_thumbs(projects)
        kept = len(projects) - len(cached)
        print(f"  --no-shoot: reused {kept} cached thumbnails, "
              f"{len(cached)} without preview")
    else:
        asyncio.run(shoot.shoot(projects, args.concurrency))
    # Full scans only: the project list is the complete picture, so anything
    # it does not reference is safe to drop.
    gone, freed = shoot.gc_thumbs(projects)
    if gone:
        print(f"  cleaned {gone} stale thumbnail(s) ({freed / 1e6:.1f} MB)")
    build.build(projects, [str(r) for r in rs])
    print("done.")


def _cmd_serve(args):
    from . import serve as serve_mod
    serve_mod.serve(port=args.port, open_browser=not args.no_open)


def _cmd_open(_args):
    if not INDEX.exists():
        print("! no dashboard built yet. run: artifold scan")
        return 1
    url = INDEX.as_uri()
    print(url)
    webbrowser.open(url)


def _cmd_designs(args):
    """List or dump design fingerprints. Designs are extracted at scan time,
    cached in the provenance store, keyed by content SHA1.

    Stable contracts for the /craft skill (and any other automation):
      artifold designs --json              → JSON array of {id,name,dir,category,palette,fonts,flags...}
      artifold designs --axes --limit 12   → slim rows: just the five rotation axes
      artifold designs <id>                → JSON fingerprint object (always JSON; default)
      artifold designs <id> --template     → raw text (CSS + skeleton); paste into LLM
      artifold designs <id> --css          → raw CSS only
      artifold designs <id> --skeleton     → raw skeleton only
    """
    from . import design, provenance
    from .paths import DATA
    import json

    # Build a lookup: short sha → (path, project) using the latest scan.
    by_sha: dict[str, dict] = {}
    if DATA.exists():
        d = json.loads(DATA.read_text())
        for proj in d.get("projects") or []:
            for v in proj.get("versions") or [proj.get("primary")]:
                sha = (v or {}).get("sha1")
                if sha:
                    by_sha[sha] = {"path": v["path"], "name": proj["name"],
                                    "dir": proj["dir"],
                                    "category": proj.get("category"),
                                    "version": v.get("version", 1)}

    if not args.id:
        # list mode
        items = provenance.all_items()
        rows = []
        for sha, entry in items.items():
            d = entry.get("design") or {}
            if not d:
                continue
            # Superseded = an in-place edit migrated this entry to a new
            # hash; orphaned = the content vanished. Either way it isn't a
            # live artifact; listing it produced the name:"?" rows.
            if entry.get("superseded_by") or entry.get("orphaned_at"):
                continue
            info = by_sha.get(sha, {})
            rows.append({
                "id": sha[:8],
                "name": info.get("name", "?"),
                "dir": info.get("dir", ""),
                "category": info.get("category"),
                "palette": d.get("palette", []),
                "fonts": d.get("fonts", []),
                "flags": {k: bool(d.get(k)) for k in
                          ("themed", "gradient", "glass", "animated", "shadowed")},
                # Critical for /craft: all four composition axes of recent
                # outputs, so the next invocation can rotate every axis
                # from one call instead of grepping inbox files.
                "design_mode":      entry.get("design_mode"),
                "voice_register":   entry.get("voice_register"),
                "layout_archetype": entry.get("layout_archetype"),
                "signature_device": entry.get("signature_device"),
                "scale":            entry.get("scale"),
                "conceit":          entry.get("conceit"),
                "tool":             entry.get("tool"),
                "added_at":         entry.get("added_at"),
            })
        # Sort recent-first so the skill can grab "last 3 /craft" trivially.
        rows.sort(key=lambda r: r.get("added_at") or "", reverse=True)
        if getattr(args, "limit", 0):
            rows = rows[:args.limit]
        if args.json:
            # --axes: the projection /craft actually consumes. The full rows
            # carry a palette and flag block per artifact, which on a real
            # library (90+ artifacts, growing ~37/month) meant ~62 KB of JSON
            # read into context on every single invocation just to answer
            # "what did the last few pages look like?". This keeps that call
            # flat in size as the library grows.
            if getattr(args, "axes", False):
                keys = ("id", "name", "scale", "layout_archetype",
                        "design_mode", "voice_register", "signature_device",
                        "conceit", "added_at")
                rows = [{k: r.get(k) for k in keys} for r in rows]
            print(json.dumps(rows, indent=2))
            return 0
        if not rows:
            print("(no design fingerprints yet — run `artifold scan`)")
            return 0
        print(f"  {'id':<10}{'name':<40}{'palette':<28}flags")
        for r in rows[:60]:
            sig = " ".join(k for k, v in r["flags"].items() if v)
            pal = " ".join(r["palette"][:4])
            print(f"  {r['id']:<10}{r['name'][:38]:<40}{pal:<28}{sig}")
        return 0

    # single-artifact mode
    target_sha = next((s for s in provenance.all_items()
                       if s.startswith(args.id)), None)
    if not target_sha:
        msg = {"error": f"no artifact found with id starting {args.id!r}",
               "hint": "run `artifold designs` to list available ids"}
        print(json.dumps(msg) if args.json else f"  ! {msg['error']}\n    {msg['hint']}")
        return 1
    info = by_sha.get(target_sha, {})
    if args.template or args.css or args.skeleton:
        if not info.get("path"):
            print(f"  ! no current file path for {target_sha[:8]} "
                  f"— run `artifold scan` first")
            return 1
        html = Path(info["path"]).read_text(encoding="utf-8", errors="ignore")
        if args.css:
            for s in design.STYLE_RE.findall(html):
                print(s.strip())
        elif args.skeleton:
            print(design.as_template(html, include_css=False, include_skeleton=True))
        else:
            print(design.as_template(html))
        return 0
    # default: structured JSON for the fingerprint (already machine-readable)
    entry = provenance.get(target_sha) or {}
    d = entry.get("design") or {}
    print(json.dumps({"sha1": target_sha, **info, **d}, indent=2))
    return 0


def _cmd_search(args):
    """Search the library by keyword. The main consumer is automation
    (/craft's "does this already exist?" check before generating a new
    artifact), so --json is a stable contract: a JSON array of
    {id, name, path, dir, category, intent, version_count, mtime, score},
    best match first. Terms are ANDed; each must hit at least one field.
    """
    import json
    from datetime import datetime
    from .paths import DATA

    if not DATA.exists():
        msg = "no scan data yet; run `artifold scan`"
        print(json.dumps({"error": msg}) if args.json else f"! {msg}")
        return 1
    d = json.loads(DATA.read_text())
    terms = [t.lower() for t in args.query if t.strip()]
    if not terms:
        print("! pass one or more search words")
        return 1

    # field weight: identity > curation > content > prompt
    WEIGHTS = (("name", 5), ("meta", 3), ("intent", 3),
               ("content", 2), ("prompt", 1))

    def fields_of(p: dict) -> dict[str, str]:
        prov = (p.get("primary") or {}).get("provenance") or {}
        return {
            "name":    p.get("name", ""),
            "meta":    " ".join([p.get("dir", ""), p.get("category") or "",
                                 *(prov.get("tags") or []),
                                 *(prov.get("topic") or [])]),
            "intent":  prov.get("intent") or "",
            "content": p.get("search_text", ""),
            "prompt":  prov.get("prompt") or "",
        }

    hits = []
    for p in d.get("projects") or []:
        fs = {k: v.lower() for k, v in fields_of(p).items()}
        score = 0
        for t in terms:
            t_score = sum(w for k, w in WEIGHTS if t in fs[k])
            if t_score == 0:
                score = 0
                break
            score += t_score
        if score:
            hits.append((score, p))
    hits.sort(key=lambda sp: (-sp[0], -sp[1].get("latest_mtime", 0)))
    hits = hits[:args.limit]

    if args.json:
        out = [{
            "id": p["id"],
            "name": p["name"],
            "path": p["primary"]["path"],
            "dir": p.get("dir", ""),
            "category": p.get("category"),
            "intent": ((p.get("primary") or {}).get("provenance") or {}).get("intent"),
            "version_count": p.get("version_count", 1),
            "mtime": p.get("latest_mtime"),
            "score": s,
        } for s, p in hits]
        print(json.dumps(out, indent=2))
        return 0 if out else 1
    if not hits:
        print(f"(no matches for {' '.join(terms)!r})")
        return 1
    for s, p in hits:
        when = datetime.fromtimestamp(p.get("latest_mtime", 0)).strftime("%Y-%m-%d")
        vers = f"  ({p['version_count']} versions)" if p.get("version_count", 1) > 1 else ""
        print(f"  {p['name'][:56]:<58}{when}{vers}")
        intent = ((p.get("primary") or {}).get("provenance") or {}).get("intent")
        if intent:
            print(f"    {intent}")
        print(f"    {p['primary']['path']}")
    return 0


def _cmd_install_skill(args):
    """Copy the bundled /craft Claude Code skill into ~/.claude/skills/.

    The skill is SKILL.md (the procedure) plus references/*.md (the layout /
    mode / device / font / recipe catalogs it reads at compose time) — all
    of them install together or the skill runs blind."""
    from importlib import resources
    pkg = resources.files("artifold.skills.craft")
    dest_dir = Path(args.dest).expanduser() if args.dest else \
               Path.home() / ".claude" / "skills" / "craft"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "SKILL.md"
    if dest.exists() and not args.force:
        print(f"  ! already installed at {dest}")
        print(f"    pass --force to overwrite")
        return 1
    dest.write_text(pkg.joinpath("SKILL.md").read_text(encoding="utf-8"),
                    encoding="utf-8")
    refs = pkg.joinpath("references")
    n_refs = 0
    if refs.is_dir():
        (dest_dir / "references").mkdir(exist_ok=True)
        for f in refs.iterdir():
            if f.name.endswith(".md"):
                (dest_dir / "references" / f.name).write_text(
                    f.read_text(encoding="utf-8"), encoding="utf-8")
                n_refs += 1
    print(f"  installed /craft skill → {dest}"
          + (f"  (+{n_refs} reference catalogs)" if n_refs else ""))
    print()
    print("  Try it in Claude Code:")
    print("    /craft a 30-day strength tracker for a beginner")
    print("    /craft a one-pager comparing SF apartments")
    print("    /craft an explainer of how transformers work, like dobble")
    print()
    print("  The skill will consult your Artifold library for style references")
    print("  by default; pass a reference explicitly with `like <id-or-name>`.")
    return 0


# Design skills Artifold knows about. Artifold indexes the output of any of
# them; this table is about how much *meaning* survives the handoff, which
# depends entirely on whether the skill records anything at generation time.
#
# Star counts are a snapshot (Sept 2026) and only there to say "these are the
# popular ones", not to rank them. Two of the three biggest write nothing
# into their output and keep no memory between runs — which is precisely the
# gap a library fills.
KNOWN_SKILLS = [
    {"name": "craft", "repo": "bundled with artifold", "stars": None,
     "dir": "craft", "support": "native",
     "note": "emits all 9 tags; full search, facets and axis rotation"},
    {"name": "hallmark", "repo": "Nutlope/hallmark", "stars": "27.7k",
     "dir": "hallmark", "support": "adapter",
     "note": "CSS stamp + .hallmark/log.json read for layout, theme, brief"},
    {"name": "taste-skill", "repo": "Leonxlnx/taste-skill", "stars": "83.3k",
     "dir": "taste-skill", "support": "fingerprint",
     "note": "writes no marker; palette/fonts/skeleton recovered from HTML"},
    {"name": "huashu-design", "repo": "alchaincyf/huashu-design", "stars": "23.8k",
     "dir": "huashu-design", "support": "fingerprint",
     "note": "writes no marker; palette/fonts/skeleton recovered from HTML"},
    {"name": "styleseed", "repo": "bitjaru/styleseed", "stars": "936",
     "dir": "styleseed", "support": "fingerprint",
     "note": "keeps STYLESEED.md for consistency, not per-run variety"},
]

SUPPORT_BLURB = {
    "native":      "everything: intent, conceit, 4 axes, rotation",
    "adapter":     "layout, theme and brief, read from its own stamp",
    "fingerprint": "palette, fonts, tokens, skeleton, thumbnail, search",
}


def _cmd_config(args):
    """Read or write a scalar setting.

    `artifold config publish` prints `on`/`off` — the form /craft calls before
    deciding whether to publish an artifact. Booleans print as on/off rather
    than True/False so a shell test reads naturally.
    """
    def show(v):
        return ("on" if v else "off") if isinstance(v, bool) else \
               ("" if v is None else str(v))

    if not args.key:
        cfg = config.load()
        for k in sorted(config.SETTABLE):
            print(f"  {k:<20}{show(cfg.get(k, config.DEFAULTS.get(k)))}")
        return 0
    try:
        if args.value is None:
            print(show(config.get(args.key)))
        else:
            print(show(config.set_(args.key, args.value)))
    except KeyError:
        print(f"  ! unknown key: {args.key}")
        print(f"    known: {', '.join(sorted(config.SETTABLE))}")
        return 1
    except ValueError as e:
        print(f"  ! {e}")
        return 1
    return 0


def _cmd_skills(args):
    """Show which design skills are installed and what Artifold recovers.

    Artifold does not care which skill made a page — it indexes any HTML.
    What differs is how much survives: a skill that states its intent gives
    you a searchable library, one that states nothing gives you a pretty
    grid. This command makes that difference visible before you pick.
    """
    skills_dir = Path.home() / ".claude" / "skills"
    installed = {p.name for p in skills_dir.iterdir()} if skills_dir.is_dir() else set()

    print("  Design skills — Artifold indexes output from any of them.")
    print("  What changes is how much meaning survives the handoff.\n")
    print(f"  {'':<2}{'skill':<16}{'stars':<8}{'artifold reads':<16}source")
    print(f"  {'':<2}{'-'*15:<16}{'-'*7:<8}{'-'*15:<16}{'-'*28}")
    for s in KNOWN_SKILLS:
        mark = "✓" if s["dir"] in installed else " "
        stars = s["stars"] or "—"
        print(f"  {mark:<2}{s['name']:<16}{stars:<8}{s['support']:<16}{s['repo']}")
    print()
    for s in KNOWN_SKILLS:
        if s["dir"] in installed:
            print(f"  {s['name']}: {s['note']}")
    if not installed & {s["dir"] for s in KNOWN_SKILLS}:
        print("  None of these are installed yet.")
    print()
    print("  native      — " + SUPPORT_BLURB["native"])
    print("  adapter     — " + SUPPORT_BLURB["adapter"])
    print("  fingerprint — " + SUPPORT_BLURB["fingerprint"])
    print()
    print("  Install the bundled one:   artifold install-skill")
    print("  Install any other:         npx skills add <repo>")
    print("  Teach your own skill to record intent:")
    print("    https://github.com/shubhamgoel27/artifold/blob/main/docs/ARTIFACT-METADATA.md")
    return 0


def _cmd_inbox(args):
    """Print the canonical path for a new artifact (date-prefixed slug).

    Used by the /craft skill (and humans) to keep all generated artifacts
    in one place with sortable filenames. Auto-creates ~/artifold-inbox/
    and adds it as a root the first time it's needed.
    """
    import re
    from datetime import datetime
    cfg = config.load()
    if cfg.get("drop_dir"):
        inbox = Path(cfg["drop_dir"]).expanduser().resolve()
    else:
        inbox = (Path.home() / "artifold-inbox").resolve()
    inbox.mkdir(parents=True, exist_ok=True)
    # Ensure inbox is a watched root (so the artifact auto-indexes when written)
    roots = [str(Path(r).expanduser().resolve()) for r in (cfg.get("roots") or [])]
    if str(inbox) not in roots:
        config.add_root(inbox)
        fresh = config.load()
        if not fresh.get("drop_dir"):
            fresh["drop_dir"] = str(inbox)
            config.save(fresh)
    topic = " ".join(args.topic) if args.topic else "untitled"
    slug = re.sub(r"[^\w\s-]", "", topic.lower()).strip()
    slug = re.sub(r"\s+", "-", slug)[:60].strip("-") or "untitled"
    date = datetime.now().strftime("%Y-%m-%d")
    path = inbox / f"{date}-{slug}.html"
    # Disambiguate if a file with that exact name already exists today
    i = 2
    while path.exists():
        path = inbox / f"{date}-{slug}-{i}.html"
        i += 1
    print(path)
    return 0


def _cmd_doctor(_args):
    from . import diagnostics
    print(f"Artifold diagnostics (config: {diagnostics.CONFIG_FILE})\n")
    checks = diagnostics.run_all()
    fails, warns = diagnostics.report(checks)
    print()
    if fails == 0 and warns == 0:
        print("all good ✓")
        return 0
    print(f"{fails} blocker(s), {warns} warning(s).")
    return 0 if fails == 0 else 1


def _cmd_trash(args):
    """Move an HTML artifact to the system Trash (recoverable)."""
    from . import trash as trash_mod
    src = Path(args.path).expanduser().resolve()
    if not args.yes:
        # Bare confirmation — show what we're about to do, ask y/N
        sz = src.stat().st_size if src.is_file() else 0
        print(f"  move to Trash: {src}  ({sz:,} bytes)")
        try:
            ans = input("  proceed? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "n"
        if ans not in ("y", "yes"):
            print("  cancelled.")
            return 1
    ok, msg = trash_mod.trash_file(src)
    if not ok:
        print(f"  ! {msg}")
        return 1
    print(f"  ✓ trashed: {src}")
    return 0


def _cmd_export_pdf(args):
    """Render an HTML artifact to PDF via headless chromium."""
    from . import pdf as pdf_mod
    src = Path(args.path).expanduser().resolve()
    if not src.is_file():
        print(f"  ! not a file: {src}")
        return 1
    out = Path(args.out).expanduser().resolve() if args.out else None
    try:
        result = pdf_mod.export_pdf(
            src,
            out=out,
            format=args.format,
            landscape=args.landscape,
            print_backgrounds=not args.no_backgrounds,
            margin=args.margin,
        )
    except ValueError as e:
        print(f"  ! {e}")
        return 1
    except Exception as e:
        print(f"  ! export failed: {type(e).__name__}: {e}")
        return 1
    sz = result.stat().st_size
    print(f"  ✓ {result}  ({sz:,} bytes)")
    if args.open:
        import platform, subprocess
        if platform.system().lower() == "darwin":
            subprocess.Popen(["open", str(result)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 0


def _cmd_share(args):
    from . import share
    if args.list:
        items = share.list_shares()
        if not items:
            print("(no shares yet)")
            return 0
        for it in items:
            print(f"  {it['id']}  {it['url']}")
            if it.get("source"):
                print(f"           src: {it['source']}")
        return 0
    if args.revoke:
        return 0 if share.revoke(args.revoke) else 1
    if not args.file:
        print("! pass a file to share, or --list / --revoke <id>")
        return 1
    url = share.share_via_gh(Path(args.file), no_clipboard=args.no_clipboard)
    return 0 if url else 1


def _cmd_import(args):
    from . import importer
    out = importer.import_url(args.url, name=args.name, drop_dir=args.drop_dir)
    return 0 if out else 1


def _cmd_link(args):
    """Attach provenance (source URL / tool / model / prompt) to a file."""
    p = Path(args.file).expanduser().resolve()
    if not p.is_file():
        print(f"! not a file: {p}")
        return 1
    fields = {k: v for k, v in {
        "source": args.source, "tool": args.tool,
        "model": args.model, "prompt": args.prompt,
        "notes": args.note,
    }.items() if v}
    if args.tag:
        fields["tags"] = list(args.tag)
    if not fields:
        print("! nothing to set — pass at least one of --source/--tool/"
              "--model/--prompt/--tag/--note")
        return 1
    try:
        sha, entry = provenance.annotate_path(p, **fields)
    except ValueError as e:
        print(f"! {e}")
        return 1
    print(f"linked {p}")
    print(f"  sha1: {sha}")
    for k in ("source", "tool", "model", "tags", "prompt", "notes"):
        if entry.get(k):
            v = entry[k]
            if isinstance(v, str) and len(v) > 80:
                v = v[:77] + "…"
            print(f"  {k}: {v}")


def _cmd_info(args):
    """Show provenance + project info for a file.

    With --json, emits the full provenance entry plus sha1 + path as a
    stable JSON document (for scripts and the /craft skill).
    """
    import json
    p = Path(args.file).expanduser().resolve()
    if not p.is_file():
        msg = f"not a file: {p}"
        print(json.dumps({"error": msg}) if args.json else f"! {msg}")
        return 1
    sha = provenance.sha1_of(p)
    entry = provenance.get(sha) or {}
    if args.json:
        print(json.dumps({"path": str(p), "sha1": sha, **entry}, indent=2))
        return 0
    print(f"file:    {p}")
    print(f"sha1:    {sha}")
    if not entry:
        print("(no provenance attached — run `artifold link <file> ...`)")
        return 0
    for k in ("source", "tool", "model", "tags", "prompt", "notes", "added_at"):
        if entry.get(k) is not None:
            print(f"{k+':':9}{entry[k]}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="artifold",
        description="Local-first library for your AI-generated HTML artifacts.")
    p.add_argument("--version", action="version", version=f"artifold {__version__}")
    sub = p.add_subparsers(dest="cmd")

    init_p = sub.add_parser("init", help="initialize Artifold (interactive wizard)")
    init_p.add_argument("--non-interactive", action="store_true",
                        help="skip prompts; just create the config dir")
    init_p.set_defaults(fn=_cmd_init)

    a = sub.add_parser("add", help="add a root directory")
    a.add_argument("path"); a.set_defaults(fn=_cmd_add)

    r = sub.add_parser("remove", help="remove a root directory")
    r.add_argument("path"); r.set_defaults(fn=_cmd_remove)

    sub.add_parser("roots", help="list configured roots").set_defaults(fn=_cmd_roots)

    al = sub.add_parser("allow-repo",
                        help="include a git-repo subdir in scans (no arg = list)")
    al.add_argument("name", nargs="?",
                    help="subdir name to allow-list (e.g. `frontier-lab-prep`)")
    al.set_defaults(fn=_cmd_allow_repo)

    da = sub.add_parser("disallow-repo",
                        help="remove a name from the allow-list")
    da.add_argument("name")
    da.set_defaults(fn=_cmd_disallow_repo)

    s = sub.add_parser("scan", help="scan + screenshot + build dashboard")
    s.add_argument("--no-shoot", action="store_true",
                   help="skip screenshots; reuse cached thumbnails")
    s.add_argument("--concurrency", type=int, default=5)
    g = s.add_mutually_exclusive_group()
    g.add_argument("--intent", action="store_true",
                   help="force-enable LLM intent inference for this run "
                        "(needs ANTHROPIC_API_KEY)")
    g.add_argument("--no-intent", action="store_true",
                   help="force-skip LLM intent inference for this run")
    s.set_defaults(fn=_cmd_scan)

    v = sub.add_parser("serve", help="live dashboard with auto-rescan")
    v.add_argument("--port", type=int, default=8787)
    v.add_argument("--no-open", action="store_true",
                   help="don't auto-open the browser")
    v.set_defaults(fn=_cmd_serve)

    sub.add_parser("open", help="open the dashboard in your browser").set_defaults(fn=_cmd_open)
    sub.add_parser("doctor", help="check setup; show fixes for anything missing").set_defaults(fn=_cmd_doctor)

    tr = sub.add_parser("trash",
                        help="move an HTML artifact to the system Trash (recoverable)")
    tr.add_argument("path", help="path to the .html file")
    tr.add_argument("-y", "--yes", action="store_true",
                    help="skip confirmation prompt")
    tr.set_defaults(fn=_cmd_trash)

    ep = sub.add_parser("export-pdf",
                        help="render an HTML artifact to PDF (next to source by default)")
    ep.add_argument("path", help="path to the .html file")
    ep.add_argument("--out", help="output path (default: <source-dir>/<stem>.pdf)")
    ep.add_argument("--format", default="A4",
                    choices=["A4", "Letter", "Legal", "Tabloid", "A3", "A5"])
    ep.add_argument("--landscape", action="store_true", help="landscape orientation")
    ep.add_argument("--margin", default="12mm",
                    help="page margin (e.g. 12mm, 0.5in, 0) — applies to all sides")
    ep.add_argument("--no-backgrounds", action="store_true",
                    help="print without background colors/images (smaller, may break design)")
    ep.add_argument("--open", action="store_true",
                    help="open the PDF in the system default viewer after export")
    ep.set_defaults(fn=_cmd_export_pdf)

    ib = sub.add_parser("inbox",
        help="print the canonical path for a new artifact (date-prefixed slug)")
    ib.add_argument("topic", nargs="*",
                    help="topic words → filename slug (defaults to 'untitled')")
    ib.set_defaults(fn=_cmd_inbox)

    cf = sub.add_parser("config", help="read or write a setting (no args lists them)")
    cf.add_argument("key", nargs="?", help="e.g. publish")
    cf.add_argument("value", nargs="?", help="omit to read; on/off for switches")
    cf.set_defaults(fn=_cmd_config)

    sub.add_parser("skills",
                   help="design skills Artifold works with, and what it reads "
                        "from each").set_defaults(fn=_cmd_skills)

    isk = sub.add_parser("install-skill",
        help="install the /craft Claude Code skill into ~/.claude/skills/")
    isk.add_argument("--dest", help="install to a specific path "
                                     "(default: ~/.claude/skills/craft/)")
    isk.add_argument("--force", action="store_true", help="overwrite if present")
    isk.set_defaults(fn=_cmd_install_skill)

    se = sub.add_parser("search",
        help="search the library by keyword (title, content, intent, tags)")
    se.add_argument("query", nargs="+", help="search words (ANDed)")
    se.add_argument("--json", action="store_true",
                    help="machine-readable JSON output (stable contract for scripts/skills)")
    se.add_argument("--limit", type=int, default=10, help="max results (default 10)")
    se.set_defaults(fn=_cmd_search)

    dg = sub.add_parser("designs", help="list or dump design fingerprints (style + skeleton)")
    dg.add_argument("id", nargs="?", help="artifact id prefix (from `artifold designs`)")
    dg.add_argument("--json", action="store_true",
                    help="machine-readable JSON output (stable contract for scripts/skills)")
    dg.add_argument("--limit", type=int, default=0, metavar="N",
                    help="only the N most recent artifacts (0 = all)")
    dg.add_argument("--axes", action="store_true",
                    help="slim rows: just the rotation axes, no palette/flags "
                         "(what /craft needs; ~95%% smaller)")
    dg_g = dg.add_mutually_exclusive_group()
    dg_g.add_argument("--template", action="store_true",
                      help="dump CSS + body skeleton (paste into Claude as style example)")
    dg_g.add_argument("--css", action="store_true",
                      help="dump just the <style> contents")
    dg_g.add_argument("--skeleton", action="store_true",
                      help="dump just the body skeleton (no text)")
    dg.set_defaults(fn=_cmd_designs)

    lk = sub.add_parser("link", help="attach source URL / tool / prompt to a file")
    lk.add_argument("file")
    lk.add_argument("--source", help="chat or artifact URL")
    lk.add_argument("--tool", choices=["claude", "chatgpt", "v0", "lovable",
                                         "bolt", "gemini", "cursor", "manual"],
                    help="generating tool")
    lk.add_argument("--model", help="model id (e.g. claude-opus-4-7)")
    lk.add_argument("--prompt", help="the prompt that produced it")
    lk.add_argument("--tag", action="append", default=[], help="add a tag (repeatable)")
    lk.add_argument("--note", help="free-form note")
    lk.set_defaults(fn=_cmd_link)

    inf = sub.add_parser("info", help="show provenance for a file")
    inf.add_argument("file")
    inf.add_argument("--json", action="store_true",
                     help="JSON output (stable contract for scripts/skills)")
    inf.set_defaults(fn=_cmd_info)

    sh = sub.add_parser("share", help="publish an artifact to a public URL (GitHub Pages)")
    sh.add_argument("file", nargs="?", help="HTML file to share")
    sh.add_argument("--list", action="store_true", help="list previous shares")
    sh.add_argument("--revoke", metavar="ID", help="delete a previously-shared artifact")
    sh.add_argument("--no-clipboard", action="store_true",
                    help="don't copy the URL to clipboard")
    sh.set_defaults(fn=_cmd_share)

    im = sub.add_parser("import", help="fetch a shared AI-artifact URL into your library")
    im.add_argument("url")
    im.add_argument("--name", help="override filename (no .html needed)")
    im.add_argument("--drop-dir", help="save into this dir (defaults to ~/artifold-inbox)")
    im.set_defaults(fn=_cmd_import)

    args = p.parse_args(argv)
    if not getattr(args, "fn", None):
        # default: serve (initial scan happens inside if no dashboard yet)
        return _cmd_serve(argparse.Namespace(port=8787, no_open=False))
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
