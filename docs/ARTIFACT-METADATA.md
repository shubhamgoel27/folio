# Artifact metadata

A four-line convention that lets a generated HTML page say what it is.

This is written for people building **design skills** — Claude Code skills,
Cursor rules, Codex prompts, anything that emits a single-file HTML page.
You do not need Artifold to use it, and Artifold is not required to read it.
It is plain `<meta>` tags.

## Why bother

A design skill knows things at generation time that are expensive or
impossible to recover afterwards: what the user asked for, which layout it
picked, which palette family it committed to, whether it was aiming for a
quick reference card or a showpiece. The moment the file is written, all of
that is gone. A reader is left inferring intent from `<h1>` tags.

That loss has a practical cost. It is why most design skills cannot rotate
away from what they did last time — they have no record of last time.

## The tags

Put these in `<head>`. All are optional; emit what you know.

```html
<meta name="artifold:intent"    content="Six-day road trip itinerary for two">
<meta name="artifold:generator" content="hallmark">
<meta name="artifold:tool"      content="claude">
<meta name="artifold:prompt"    content="Plan the Chicago trip, we fly Monday">
```

That is the useful minimum. `intent` is the one that matters most: one
sentence, 10–15 words, describing what the page is *for*. Not its title.

### Full field list

| Tag | Meaning |
|---|---|
| `intent` | One line: what this page is for. The highest-value field. |
| `generator` | The skill that built it (`craft`, `hallmark`, `taste-skill`). |
| `tool` | The model vendor underneath (`claude`, `chatgpt`, `gemini`, `v0`). |
| `model` | Specific model id, if you know it. |
| `prompt` | The user's request, trimmed to ~200 characters. |
| `source` | Chat or artifact URL this came from. |
| `conceit` | The one-line idea the page commits to, if it has one. |
| `scale` | How much page this is: `glance`, `read`, or `experience`. |
| `layout-archetype` | The page skeleton you chose. Your vocabulary, not ours. |
| `design-mode` | The skin: palette and type family. |
| `voice-register` | The tone of the copy. |
| `signature-device` | The one built thing on the page. |
| `published` | URL where this page is hosted, if the generator published it. |
| `style-from` | Id of a past artifact this deliberately echoes. |

The last four are **rotation axes**. Their whole purpose is to be read back
on the next run so you can pick something different. The values are yours —
we do not define a vocabulary. `macrostructure: Marquee Hero` and
`layout-archetype: card-stack-dossier` are both fine. What matters is that
the same skill uses the same words consistently, so "not this again" is
computable.

### A note on `published`

`published` says "this page also exists at this URL". It does **not** mean
the page is public — a claude.ai artifact is private to its author until they
share it, and a reader has no way to tell from the tag. So treat it as a
convenience link back to your own copy, and don't render it as a public-share
badge. Artifold keeps it deliberately separate from its own share records for
this reason.

If your generator can publish, writing this tag is the difference between an
artifact the user can send someone and one they have to hunt for.

### Conventions

- Values are plain text. Escape quotes; keep each under ~200 characters.
- Emit nothing rather than emit a guess. An absent tag is honest; a wrong
  `intent` poisons every search that follows.
- `folio:` is accepted as a legacy prefix for all of these.

## Reading them back

Any regex will do. `<meta\s+name=["']artifold:intent["']\s+content=["']([^"']+)["']`
gets you there. If you want the rest for free:

```bash
pip install artifold
artifold scan
artifold designs --json --axes --limit 12   # your last 12 runs, all axes
```

That last command is the rotation loop. It returns the axes of recent
artifacts across your whole machine, so the next build can avoid repeating
any of them.

## If your skill already stamps its own format

You do not have to change anything. Artifold reads foreign markers through
adapters in `artifold/adapters.py`. Hallmark's CSS stamp and
`.hallmark/log.json` are supported today.

Adding one is about thirty lines: a function that takes `(html, path)` and
returns a dict, plus an entry in `ADAPTERS`. Mapping into the field names
above is lossy on purpose, so the raw values are preserved under
`generator_native`. Pull requests welcome — and a skill that emits the tags
directly will always beat an adapter, because it does not have to guess.
