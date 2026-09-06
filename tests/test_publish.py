"""Tests for the published-artifact link and the `publish` setting.

Artifold cannot publish anything — publishing needs a claude.ai session and
the CLI has none. What it does is *record* a link the `/craft` skill wrote,
because the skill runs inside Claude Code where that session exists.

The distinction these tests protect: **published is not shared**. A claude.ai
artifact is private to its author until they share it from the page header,
so a published URL must never light up the "shared publicly" state.
"""
import pytest

from artifold import config, detect, provenance, scan

URL = "https://claude.ai/code/artifact/5fbea6f3-0000-4000-8000-000000000000"


def page(extra=""):
    return (f'<!doctype html><html><head><title>T</title>'
            f'<meta name="artifold:intent" content="a probe">{extra}'
            f'<style>body{{color:#123456}}</style></head>'
            f'<body><h1>T</h1></body></html>')


# --- the tag ---------------------------------------------------------------

def test_published_tag_is_parsed():
    html = page(f'<meta name="artifold:published" content="{URL}">')
    assert detect.extract_embedded_meta(html)["published_url"] == URL


def test_absent_tag_yields_nothing():
    assert "published_url" not in detect.extract_embedded_meta(page())


def test_legacy_folio_prefix_works():
    html = page(f'<meta name="folio:published" content="{URL}">')
    assert detect.extract_embedded_meta(html)["published_url"] == URL


def test_published_is_not_source(tmp_path):
    """`source` is where it came from; `published` is where it now lives."""
    m = detect.extract_embedded_meta(
        page(f'<meta name="artifold:published" content="{URL}">'))
    assert m.get("source") is None


# --- reaching the dashboard ------------------------------------------------

@pytest.fixture
def scanned(tmp_path):
    def run(extra=""):
        (tmp_path / "a.html").write_text(page(extra))
        return scan._scan_root(tmp_path, {"allow_repos": [], "max_depth": 3},
                               {}, {})[0]
    return run


def test_link_reaches_the_project_payload(scanned):
    proj = scanned(f'<meta name="artifold:published" content="{URL}">')
    assert proj["primary"]["provenance"]["published_url"] == URL


def test_publishing_does_not_mark_an_artifact_as_shared(scanned):
    """The green share dot means public. Published does not."""
    prov = scanned(f'<meta name="artifold:published" content="{URL}">')["primary"]["provenance"]
    assert not prov.get("shares")


def test_link_backfills_if_it_is_stamped_after_saving(tmp_path):
    """Stamping the tag onto an already-saved file still works — but note the
    cost this documents: the edit is a second content hash, so the artifact
    gains a revision it did not earn, inflating its badge and its "Most used"
    rank. That is why the skill publishes from the temp path and writes the
    inbox copy once, with the tag already in it."""
    f = tmp_path / "a.html"
    cfg, cats = {"allow_repos": [], "max_depth": 3}, {}
    f.write_text(page())
    first = scan._scan_root(tmp_path, cfg, cats, {})[0]
    assert "published_url" not in (first["primary"]["provenance"] or {})

    f.write_text(page(f'<meta name="artifold:published" content="{URL}">'))
    second = scan._scan_root(tmp_path, cfg, cats, {})[0]
    assert second["primary"]["provenance"]["published_url"] == URL
    assert second["revision_count"] == 2      # same artifact, not a new one


# --- the setting -----------------------------------------------------------

def test_publish_defaults_on(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "c.json")
    assert config.get("publish") is True


def test_publish_can_be_turned_off(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "c.json")
    assert config.set_("publish", "off") is False
    assert config.get("publish") is False


@pytest.mark.parametrize("raw,expected", [
    ("on", True), ("true", True), ("yes", True), ("1", True),
    ("off", False), ("false", False), ("no", False), ("0", False),
    ("ON", True), ("  Off  ", False),
])
def test_switch_accepts_the_obvious_spellings(tmp_path, monkeypatch, raw, expected):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "c.json")
    assert config.set_("publish", raw) is expected


def test_a_nonsense_value_is_rejected_not_coerced(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "c.json")
    with pytest.raises(ValueError):
        config.set_("publish", "maybe")


def test_unknown_keys_are_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "c.json")
    with pytest.raises(KeyError):
        config.get("roots")          # lists have their own commands
    with pytest.raises(KeyError):
        config.set_("nope", "on")


def test_int_and_str_keys_coerce(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "c.json")
    assert config.set_("max_depth", "5") == 5
    assert config.set_("intent_model", "claude-haiku-4-5") == "claude-haiku-4-5"


def test_setting_survives_a_reload(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "c.json")
    config.set_("publish", "off")
    assert config.load()["publish"] is False


# --- share records must be durable -----------------------------------------
#
# Two independent ways 11 real shares went missing from a live library:
# the record was written only after a liveness check that can time out, and
# the GC was free to delete an entry that held one.

def _shared_entry(tmp_path, sha="a" * 40):
    provenance.set_(sha, path=str(tmp_path / "x.html"), shares=[
        {"host": "github_pages", "url": "https://u.github.io/artifold-share/aaaaaaaa.html",
         "id": "aaaaaaaa", "published_at": "2026-06-30T07:06:00+00:00"}])
    return sha


def test_gc_never_deletes_an_entry_holding_a_share(tmp_path):
    """The page stays on the internet whatever the local store forgets."""
    from datetime import datetime, timedelta, timezone
    sha = _shared_entry(tmp_path)
    stale = (datetime.now(timezone.utc)
             - timedelta(days=provenance.ORPHAN_TTL_DAYS + 1)).isoformat()
    raw = provenance._load_raw()
    raw["items"][sha]["orphaned_at"] = stale
    provenance._save_raw(raw)

    provenance.gc(set())                       # nothing live at all
    assert provenance.get(sha) is not None
    assert "orphaned_at" not in provenance.get(sha)


def test_gc_still_deletes_an_expired_entry_without_shares(tmp_path):
    from datetime import datetime, timedelta, timezone
    stale = (datetime.now(timezone.utc)
             - timedelta(days=provenance.ORPHAN_TTL_DAYS + 1)).isoformat()
    raw = provenance._load_raw()
    raw["items"]["b" * 40] = {"orphaned_at": stale}
    provenance._save_raw(raw)
    assert provenance.gc(set()) == 1


def test_a_share_survives_editing_the_artifact(tmp_path):
    """carry_forward must bring the URL to the new hash."""
    f = tmp_path / "x.html"
    f.write_text("<html>one</html>")
    sha = provenance.sha1_of(f)
    provenance.set_(sha, path=str(f), shares=[
        {"host": "github_pages", "url": "https://u.github.io/artifold-share/x.html",
         "id": "x", "published_at": None}])
    f.write_text("<html>two</html>")
    provenance.carry_forward(provenance.sha1_of(f), f)
    assert provenance.get(provenance.sha1_of(f))["shares"][0]["id"] == "x"


def test_list_shares_tolerates_a_recovered_record_with_no_timestamp(tmp_path):
    """Recovered records have published_at=None; sorting must not blow up."""
    from artifold import share
    provenance.set_("c" * 40, shares=[
        {"host": "github_pages", "url": "https://u.github.io/s/c.html",
         "id": "cccccccc", "published_at": None, "recovered": True}])
    provenance.set_("d" * 40, shares=[
        {"host": "github_pages", "url": "https://u.github.io/s/d.html",
         "id": "dddddddd", "published_at": "2026-06-30T07:06:00+00:00"}])
    ids = [s["id"] for s in share.list_shares()]
    assert set(ids) == {"cccccccc", "dddddddd"}
    assert ids[0] == "dddddddd"          # dated first, undated last
