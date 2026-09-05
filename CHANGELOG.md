# Changelog

## 0.12.0

Every new `/craft` artifact now gets a link, without you setting up GitHub.

### Why it works this way

Publishing to claude.ai needs a claude.ai session. Artifold is a standalone
CLI and has none — Anthropic's docs are explicit that "sessions using an API
key, gateway token, or cloud-provider credential cannot publish", and the only
artifact HTTP endpoints that exist are the admin-scoped Compliance API's list,
read and delete. There is no publish endpoint, and `artifold share --claude`
cannot be built.

`/craft` runs *inside* Claude Code, where that session does exist. So the
skill publishes, and Artifold records the result:

- **`/craft` publishes each artifact** after saving it, then stamps the URL
  into the page as `artifold:published`.
- **Artifold reads the tag** and puts a quiet `link` on the card plus a row
  in the detail pane. The link survives the round trip: the skill stamps the
  tag *after* the first scan, so the artifact picks it up as a revision
  rather than becoming a new project.
- **`artifold config publish off`** turns it off. New `artifold config`
  command reads and writes the scalar settings; with no arguments it lists
  them.

### Published is not shared

A claude.ai artifact is private to its author until they share it from the
page header. The card's `link` is deliberately not the green share dot, the
detail pane says "Private to you until you share it from the page", and the
metadata spec tells other implementers not to render it as a public badge.
Artifold's own `shares` list — GitHub Pages, explicitly published — stays the
only thing that means public.

### One correction to the README

The old claim "nothing leaves your machine unless you explicitly
`artifold share`" is no longer true with this default on, so it now says what
actually happens: Artifold itself still uploads nothing and holds no
credentials, `artifold share` publishes to your GitHub Pages, and `/craft`
publishes privately to claude.ai unless you turn it off.

## 0.11.0

**Scans are 9× faster: 1.63 s → 0.18 s** on a 135-project library. Cards
now say what an artifact is, not just when it was made.

### The scan was rewriting the whole store 273 times

Profiling found the cost was not the filesystem walk or the HTML parsing.
Every file's enrichment called `set_`, and every `set_` re-serialised the
entire 546 KB provenance store: 273 writes in one scan, 75% of total time.

- Provenance writes are batched. A scan collects mutations in memory and
  flushes once. Everything written during a scan is derived from files on
  disk, so a crash mid-batch costs one scan and the next one rebuilds it.
- Design fingerprints are cached by content hash instead of recomputed
  every scan. They carry a `design.SCHEMA` version, so improving
  `design.extract` later still rebuilds every fingerprint.
- `shoot` decides what needs shooting before touching the browser. It was
  spawning a `playwright install` subprocess on every scan, including the
  overwhelmingly common case where nothing had changed.

**Fixed a stale-fingerprint bug found while writing the tests for this.**
`carry_forward` copied the whole entry onto the new content hash, including
the design fingerprint describing the *old* bytes. Combined with the new
cache, an edited artifact would have kept its previous palette and fonts
indefinitely. The fingerprint is now dropped on carry-forward; source,
prompt, shares and open counts still survive, because those describe the
artifact rather than its bytes.

### The grid now says what things are

The list view has always shown each artifact's intent. The grid — the
default view — showed only a category and a timestamp, so telling two cheat
sheets apart meant opening both.

- Cards carry the intent, clamped to two lines, with the space reserved
  whether or not an artifact has one so the grid stays on one baseline.
- Artifacts in the inbox no longer render a bare `.` as their directory.
  That was roughly 90 of 135 rows showing a meaningless dot.
- The per-row `Claude` pill in list view now follows the same rule as the
  cards and the facet: it appears only when the library really was made
  with more than one tool.

## 0.10.1

**Deleting an artifact is instant now: 2,480 ms → 19 ms.**

The file was never the slow part. `POST /trash` returned in 70 ms with the
file already in the Trash, then kicked a full rescan of the library and
broadcast the result over SSE. The card only left the grid when that scan
came back, about 2.5 seconds later, so a finished delete looked like a
broken button.

- The dashboard now removes the card as soon as the request resolves. The
  rescan still runs, but as reconciliation rather than confirmation. If the
  request fails, the card comes back and the toast says why.
- `POST /trash` accepts `paths` (a list) as well as `path`. A project is
  often several files, and one request per file meant one full library
  scan per file — deleting a 3-file project scanned everything three times.
  Three files now go in one 21 ms request and trigger one scan.
- Fixed: the single-file delete path called `close()` when the last version
  went, which resolves to `window.close()`, not the detail pane's `close_()`.
  It silently did nothing instead of closing the pane.

## 0.10.0

Artifold is now the library for whatever design skill you use, not the app
that goes with `/craft`.

This came out of reading the competition properly. The design-skill
category is crowded — taste-skill has 83.3k stars, Hallmark 27.7k,
huashu-design 23.8k — and nothing at all indexes a local corpus of
AI-generated HTML. More useful still: of those three, only Hallmark
records anything between runs, and its log is per-repository. Remembering
what you already made, across projects, is the thing none of them do.

### A metadata convention anybody can emit

[`docs/ARTIFACT-METADATA.md`](docs/ARTIFACT-METADATA.md) documents the
`artifold:*` meta tags as a plain convention for design-skill authors. Four
lines of `<head>` and a generated page can say what it is for. No
dependency on Artifold to write them or to read them.

New `artifold:generator` tag names the skill that built a page, separate
from `tool`, which names the model vendor. `/craft` now emits it.

### Adapters for skills that stamp their own format

`artifold/adapters.py` reads other tools' markers. Hallmark ships first: its
CSS stamp gives layout, theme, tone and hue, and `.hallmark/log.json` gives
the brief, which lands as `intent`. Foreign vocabulary maps onto Artifold's
fields — a macrostructure is not exactly a layout archetype, so the raw
values are kept under `generator_native` rather than thrown away.

Adapters rank below native tags: a skill that states its intent always
beats one inferred from a stamp. They fail soft by design, because these
are other people's formats and they move — an unparseable stamp yields no
metadata, never an error.

### `artifold skills`

Shows which design skills you have installed and, honestly, how much
Artifold recovers from each: `native` (everything), `adapter` (layout,
theme, brief) or `fingerprint` (palette, fonts, tokens, skeleton, search).
That last tier needs no cooperation and is most of the product.

### Also

- README reframed: `/craft` is the bundled reference implementation, not
  the point. Hallmark and taste-skill are linked as real alternatives.

## 0.9.0

A second audit of a real library, five weeks and 43 artifacts after the
first. At 133 projects the questions change: not "where is it" but "which
of these do I actually use".

### Your edit history was recorded, hidden, and expiring

Artifold has always carried provenance across an in-place edit. It never
showed the result. A real library held 128 of these superseded entries —
16 artifacts with revisions, the longest chains 28 and 17 deep — while the
version dropdown, which reads `-v2` filenames, matched 2 of 133 projects.

Worse, the history was on a timer. A superseded entry's content hash is
gone from disk by definition, so the orphan rule stamped every one of them
for deletion 30 days out. All 128 were counting down.

- `gc` now exempts revisions reachable from a live artifact, and clears the
  stamp from ones already marked.
- `carry_forward` stamps `revised_at` and `superseded_at`, so the chain has
  time in it. `added_at` stays put: a revision is not a new artifact.
- Cards show a revision badge; the detail pane lists the history.

Revisions cannot be diffed — the store keeps hashes, not content — and the
pane says so instead of offering a button that cannot work. Chains recorded
before this release have no times, so that case shows the count alone.

### Artifold now knows what you use, not just what you made

Creation time cannot answer "what do I keep coming back to", and after a
hundred artifacts that is the question.

- Opening an artifact is counted, via `/open` and a `POST /opened` beacon
  for new-tab opens. Previewing a card is not an open, and revealing in
  Finder is not a read.
- New "Most used" sort, ranking opens 3× revisions. Opens start at zero
  everywhere, so revisions carry the sort until real data accrues.
- Requires `artifold serve`; a `file://` dashboard has no server to tell.

### Cache and clutter

- **Thumbnails are garbage-collected** on a full scan. The cache key is
  sha1(path+mtime+size), so every edit stranded the previous image and
  nothing ever cleaned up: 513 files, 380 of them orphans, 32.4 MB of 44 MB.
  A real library drops to 133 files and 12 MB. Stale manifest rows go too.
- **The parsed provenance store is memoized.** One scan called `_load_raw`
  670 times, re-reading 546 KB each time. Scans run in ~2.3 s where they
  took ~3.2 s, despite doing more work.
- **The tool filter and the per-card tool label hide** unless the library
  really was made with more than one tool. Reading "Claude" on 118 of 133
  cards is decoration, and a filter that cannot split anything is furniture.

## 0.8.0

The first release driven by an audit of a real library rather than a
feature list: 90 projects, ~37 added per month, three months of daily use.
It also carries everything from 0.7.0, which was built but never published.

### Categorization rewritten

Filing was wrong for roughly a fifth of the library and unhelpful for
another fifth. `_categorize` matched keywords as bare substrings and
returned the first category in dict order, so `'ai'` fired inside "wait"
and "airbnb", `'rl'` inside "ctrl", and `'ml '` inside "html ". Format
words decided subjects: a scalp-care routine filed under Finance because
the filename ended in "card", a job-application tracker under Health
because of "tracker".

- Keywords now match on whole-word boundaries, and ambiguous ones are
  phrases (`credit card`, `job application`, `real estate`).
- Every category is scored and the strongest signal wins, instead of the
  earliest dict key. Longer keywords and repeats both count for more.
- Fields are weighted by how much they're trusted to name the subject:
  path 3×, recorded intent 1.5×, body text 1×. Prose reaches for
  analogies the subject doesn't own; a health explainer written "with
  engineering analogies" is still health.
- The `intent` and `conceit` an artifact recorded about itself now feed
  the decision. They were sitting unused on 77 of 90 artifacts.
- Vocabulary rebuilt: format words (`tracker`, `guide`, `notes`, `card`,
  `review`, `story`, `explainer`) removed; domain terms added.

On the library that motivated this, clearly-misfiled projects went from 17
to 2 and the "Other" bucket from 17 to 4.

### `/craft` feedback loop

- `artifold designs --json --axes --limit N` returns just the rotation
  axes. Bare `--json` returned every row with its palette and flag block —
  ~68 KB read into context on every `/craft` invocation, growing with the
  library. The slim form is ~91% smaller and stays flat.
- `artifold:conceit` and `artifold:scale` are now parsed. `/craft` had been
  emitting both for months while `detect.py` dropped them, so no conceit
  ever reached the dashboard and the skill's own "intensity rotates too"
  rule had nothing to read. Both backfill on the next scan.
- Bundled `/craft` updated from three months of live use: a scale tier
  (`glance` / `read` / `experience`) chosen before any other rule, a
  content-editing step ahead of styling, and a CSS-first motion ladder in
  `references/motion.md` with reduced-motion and no-JS fail-safes.

### Project health

- Test suite grew from 2 files to 5 (48 tests), covering the categorizer,
  meta-tag extraction and the `designs` contract.
- GitHub Actions CI on Python 3.10–3.13, plus a build job that asserts the
  bundled skill actually ships inside the wheel.
- `pip install artifold[dev]` installs the test dependencies.

## 0.7.0

Built 2026-07-06, never published; folded into 0.8.0.

- Library intelligence: full-text `artifold search`, design fingerprints via
  `artifold designs`, and a version diff view in the dashboard.
- Grouping fix for date-prefixed slugs, so `2026-06-09-foo` and
  `2026-06-10-foo` collapse into one project with versions.
- Provenance lifecycle: entries carry forward across in-place edits and are
  marked superseded or orphaned instead of showing as `name: "?"`.
- The four-axis `/craft` skill ships inside the package
  (`artifold install-skill`).

## 0.6.2

- Card hover actions; defensive handling of malformed `data.json`.

## 0.6.1

- Trash button — move artifacts to the system Trash.

## 0.6.0

- PDF export: dashboard button, `artifold export-pdf`, and print CSS in
  `/craft`.

## 0.5.5

- Watcher robustness and a ~23× scan speedup by pruning skip-dirs during
  the walk instead of after it.

## 0.5.4

- Multi-file artifact support: sibling files and share bundling.

## 0.5.3

- `/craft` v2: design-mode and voice pickers, to fix output convergence.

## 0.5.2

- First public release.
