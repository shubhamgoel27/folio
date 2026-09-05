"""Artifold user config — roots to scan + small overrides.

config.json schema:
    {
      "roots": ["/Users/me/Downloads", "/Users/me/work"],
      "allow_repos": [],            # dir names with their own .git to include anyway
      "max_depth": 3,               # max nesting under a project dir
      "categories": { ... }         # optional override of DEFAULT_CATEGORIES
    }
"""
from __future__ import annotations

import json
from pathlib import Path

from .paths import CONFIG_FILE, ensure_dirs

# Sensible generic defaults — broad enough to cover most AI-generated artifacts.
#
# Two rules learned the hard way (see tasks/v0.8-usage-fixes.md):
#
#   1. No format words. "tracker", "guide", "notes", "card", "review",
#      "report", "story" describe an artifact's *shape*, not its subject.
#      They filed a scalp-care routine under Finance ("card") and a job
#      application tracker under Health ("tracker").
#   2. Ambiguous short words earn their keep only as phrases. Bare "credit"
#      is a tax term, a course unit, and a movie footer; "credit card" is
#      unambiguous. Keywords are matched on whole-word boundaries, so the
#      two-letter entries ("ml", "rl", "ai") are safe — they no longer fire
#      inside "html", "ctrl" or "airbnb".
#
# Order matters only for exact score ties: specific domains come before the
# catch-all Engineering bucket, which shares vocabulary with everything else.
DEFAULT_CATEGORIES = {
    "Health":      ["health", "fitness", "workout", "workouts", "exercise",
                    "diet", "nutrition", "medical", "medicine", "wellness",
                    "sleep", "mental health", "therapy", "supplement",
                    "supplements", "vitamin", "vitamins", "protein",
                    "calories", "gym", "strength training", "cardio",
                    "injury", "physio", "doctor", "symptom",
                    "symptoms", "medication", "dosage", "scalp", "hair",
                    "dermatology", "psoriasis", "greying", "graying",
                    "bloodwork", "cholesterol"],
    # Deliberately absent: "cv" (collides with computer vision), bare
    # "offer" and "application" (ordinary English, and "application layer"
    # is Engineering) — the phrase forms carry the meaning instead.
    "Career":      ["resume", "interview", "interviews", "career",
                    "job", "jobs", "hiring", "recruiter", "recruiting",
                    "promotion", "performance review", "salary",
                    "compensation", "job offer", "offer letter", "onboarding",
                    "job application", "referral", "linkedin",
                    "portfolio site", "competency", "hiring manager",
                    "behavioral", "phone screen", "star answers"],
    "Housing":     ["apartment", "apartments", "rent", "rental", "lease",
                    "real estate", "mortgage", "house", "housing",
                    "neighborhood", "neighbourhood", "landlord", "sublet",
                    "listing", "listings", "square feet"],
    "Travel":      ["trip", "travel", "itinerary", "vacation", "flight",
                    "flights", "hotel", "hostel", "road trip", "city guide",
                    "sightseeing", "packing list", "passport", "layover",
                    "airbnb"],
    "Finance":     ["finance", "financial", "tax", "taxes", "money",
                    "budget", "invest", "investing", "investment",
                    "credit card", "debit card", "loan", "retirement",
                    "401k", "roth", "stock", "stocks", "crypto",
                    "portfolio", "savings", "expense", "expenses",
                    "income", "equity", "rsu", "net worth"],
    # "explainer" is deliberately absent: it's the shape of roughly half of
    # all /craft output, not a subject. An explainer about inference belongs
    # in Engineering.
    "Education":   ["course", "courses", "lesson", "lessons", "tutorial",
                    "study", "learn", "primer", "syllabus", "curriculum",
                    "flashcards", "revision", "textbook", "coursework",
                    "lecture"],
    "Personal":    ["family", "wedding", "birthday", "anniversary", "gift",
                    "gifts", "party", "recipe", "recipes", "cooking",
                    "kitchen", "holiday", "christmas", "diwali", "photos",
                    "love letter"],
    "Engineering": ["code", "coding", "api", "agent", "agents", "ml",
                    "mlops", "model", "models", "pipeline", "algorithm",
                    "algorithms", "engineer", "engineering", "system",
                    "architecture", "infra", "infrastructure", "devops",
                    "deploy", "deployment", "kubernetes", "docker", "rl",
                    "llm", "llms", "ai", "dataset", "datasets", "embedding",
                    "embeddings", "transformer", "transformers",
                    "inference", "fine tuning", "benchmark", "eval",
                    "evals", "recsys", "ranking", "retrieval", "latency",
                    "throughput", "gpu", "database", "sql", "python",
                    "git", "compiler", "distributed", "ocr", "vlm",
                    "computer vision", "neural", "gradient descent",
                    "backprop", "backpropagation", "classifier",
                    "regression", "baseline", "labeling", "labeler",
                    "annotation", "failure analysis"],
}

DEFAULTS = {
    "roots": [],
    "allow_repos": [],
    "max_depth": 3,
    "categories": {},          # merged on top of DEFAULT_CATEGORIES
    "enable_intent": False,    # LLM-derived intent metadata (requires ANTHROPIC_API_KEY)
    "intent_model": "claude-haiku-4-5",
    "intent_concurrency": 5,
    "drop_dir": None,          # where `artifold import <url>` saves fetched artifacts
    # Whether /craft publishes each new artifact to claude.ai and records the
    # link. Artifold itself never publishes — it has no claude.ai session —
    # so this is a preference the skill reads, not something the CLI acts on.
    # Published artifacts are private to their author until shared.
    "publish": True,
}

# Config keys `artifold config` may read or write. Roots and allow-lists have
# their own commands because they are lists with validation; this is for the
# plain scalar switches.
SETTABLE = {
    "publish": bool,
    "enable_intent": bool,
    "intent_model": str,
    "intent_concurrency": int,
    "max_depth": int,
    "drop_dir": str,
}


def get(key: str):
    if key not in SETTABLE:
        raise KeyError(key)
    return load().get(key, DEFAULTS.get(key))


def set_(key: str, raw: str):
    """Coerce a CLI string into the key's type and store it."""
    if key not in SETTABLE:
        raise KeyError(key)
    kind = SETTABLE[key]
    if kind is bool:
        low = raw.strip().lower()
        if low in ("on", "true", "yes", "1"):
            value = True
        elif low in ("off", "false", "no", "0"):
            value = False
        else:
            raise ValueError(f"{key} expects on/off, got {raw!r}")
    elif kind is int:
        value = int(raw)
    else:
        value = raw
    cfg = load()
    cfg[key] = value
    save(cfg)
    return value


def load() -> dict:
    ensure_dirs()
    if not CONFIG_FILE.exists():
        return dict(DEFAULTS)
    try:
        cfg = json.loads(CONFIG_FILE.read_text())
    except Exception:
        cfg = {}
    return {**DEFAULTS, **cfg}


def save(cfg: dict) -> None:
    ensure_dirs()
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n")


def categories(cfg: dict | None = None) -> dict[str, list[str]]:
    cfg = cfg or load()
    return {**DEFAULT_CATEGORIES, **(cfg.get("categories") or {})}


def add_root(path: str | Path) -> tuple[bool, str]:
    """Add a root; returns (added?, resolved_path_str)."""
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        return False, f"not a directory: {p}"
    cfg = load()
    roots = list(cfg.get("roots") or [])
    s = str(p)
    if s in roots:
        return False, f"already configured: {s}"
    roots.append(s)
    cfg["roots"] = roots
    save(cfg)
    return True, s


def remove_root(path: str | Path) -> tuple[bool, str]:
    p = str(Path(path).expanduser().resolve())
    cfg = load()
    roots = list(cfg.get("roots") or [])
    if p not in roots:
        return False, f"not configured: {p}"
    roots.remove(p)
    cfg["roots"] = roots
    save(cfg)
    return True, p


def roots() -> list[Path]:
    return [Path(r) for r in (load().get("roots") or [])]


def add_allow_repo(name: str) -> tuple[bool, str]:
    """Add a directory NAME to the allow-list so its .git contents are
    scanned (default behavior is to skip top-level subdirs that are git
    repos, since most are cloned code rather than your artifacts)."""
    name = name.strip().strip("/")
    if not name or "/" in name:
        return False, "pass a directory name only (no slashes)"
    cfg = load()
    allow = list(cfg.get("allow_repos") or [])
    if name in allow:
        return False, f"already allow-listed: {name}"
    allow.append(name)
    cfg["allow_repos"] = sorted(allow)
    save(cfg)
    return True, name


def remove_allow_repo(name: str) -> tuple[bool, str]:
    name = name.strip().strip("/")
    cfg = load()
    allow = list(cfg.get("allow_repos") or [])
    if name not in allow:
        return False, f"not allow-listed: {name}"
    allow.remove(name)
    cfg["allow_repos"] = allow
    save(cfg)
    return True, name


def allow_repos() -> list[str]:
    return list(load().get("allow_repos") or [])
