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


def test_link_backfills_when_the_skill_stamps_it_after_saving(tmp_path):
    """/craft saves, publishes, then edits the tag in — so the file changes
    after its first scan. The link must survive that round trip."""
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
