# How It Works — Design

**Date:** 2026-05-08
**Status:** Draft for review

## Context

The site is technically interesting in ways that aren't visible from the
outside: a single Cloudflare Worker serving Zola assets and the API,
hourly cron + KV caching, a Python pipeline that scrapes pool schedules
out of SF Rec & Park PDFs, a 00:05 PT rebuild for day rollover, and
per-field stale-flag fallback when NOAA / NDBC stations go offline.

When the site gets shared on Hacker News and Lobsters, the artifact
people land on should *be* the writeup — not just the live data board.
A new top-level `/how-it-works` page becomes the share target: the same
amber-on-navy departure-board aesthetic as the rest of the site, but
turned inward to explain the micro-systems behind it.

The page is a single long-scroll reference with anchored sections so
commenters can deep-link to a specific subsystem (e.g.
`/how-it-works#pdf-parsing`).

## Goals

- One shareable URL: `swimfrancisco.com/how-it-works`.
- Reads as an extension of the site, not a docs section bolted on —
  same palette, same monospace voice, same split-flap header.
- Each section explains one micro-system with prose, real code excerpts
  pulled from the repo (linked at `file:line`), and a hand-authored SVG
  diagram in the departure-board style.
- Anchored sections so HN comments can deep-link.
- Reading time ~10 minutes. Skimmable via the section TOC.

## Non-goals

- No multi-page `/how-it-works/<topic>` section. One URL, one scroll.
- No client-side diagram rendering (no Mermaid runtime, no charting
  library). All diagrams are static inlined SVG.
- No cost / billing breakdown. That's its own future post.
- No split-flap animation deep dive. That's its own future post.
- No backend changes to the Worker, KV layout, or schedule extractor.
  This is a content-and-presentation feature.

## Page structure

Single long-scroll page with seven anchored sections:

| # | Section          | Anchor          | Words | Code | Hero diagram                            |
| - | ---------------- | --------------- | ----- | ---- | --------------------------------------- |
| 0 | Overview         | `#overview`     | ~150  | 0    | Full-system flow                        |
| 1 | One combined API | `#api`          | ~250  | 1    | Request fan-out: before vs. after       |
| 2 | Workers + KV     | `#workers`      | ~350  | 2    | Worker request lifecycle                |
| 3 | LLM PDF extraction | `#pdf-extraction` | ~500 | 3 | PDF → LLM → grounding/validation → merge |
| 4 | Caching + serving| `#cache`        | ~300  | 1    | Cron tick + KV state                    |
| 5 | Day rollover     | `#day-rollover` | ~200  | 1    | PT vs. UTC timeline                     |
| 6 | NOAA / NDBC      | `#fallback`     | ~250  | 1    | Station offline → coalesce path         |

Total: ~2,050 words, 9 code excerpts, 7 hand-authored SVG diagrams.

### Note on §3 framing

The `schedule-tools/` pipeline is not a regex/pdfplumber parser. It's
an LLM extraction (Anthropic or Gemini, configurable, with bakeoff
mode) plus a multi-stage safety net:

- **SHA-keyed PDF cache** to avoid re-extracting unchanged sources.
- **Grounding check** — every extracted session must have an evidence
  string, and the evidence's tokens must appear in order within a
  ~250-char window of the PDF text. Paraphrased answers fail.
- **Validation gate** — refuses to write if `sessions_count` drops to
  zero from a previously non-zero state (catastrophic), and warns on
  too-few sessions, invalid time ranges, multi-day closures with time
  ranges, etc.
- **Delta notes** — compares against the prior snapshot and flags
  changes for human review.
- **Reviewed-snapshot lock** — once an operator has manually verified
  a PDF's extraction, a `reviewed.json` keyed to the PDF's SHA
  fast-paths future runs (no LLM call until the PDF changes).

§3 is the longest section and the most distinctive part of the post.
"How we use LLMs to parse city PDFs and keep them honest" is the HN
hook in this section.

### Section anatomy

Every section follows the same shape so the page reads with rhythm:

1. One-sentence claim (heading + lede).
2. Hero SVG diagram (~600px wide).
3. Prose explaining the mechanism (200-400 words).
4. Code excerpt(s) with a link to the live repo at `file:line`.
5. Optional aside — a short italicized block for an anecdote, gotcha,
   or "what almost broke this." This is where the SF Rec & Parks email
   thread lives in §3.

## Diagram language

Consistent across all seven hero diagrams.

- **Background:** navy (`#1a1a2e`, the existing `theme-color`)
- **Strokes:** amber (the existing accent)
- **Boxes:** navy fill, amber stroke, monospace label
- **Arrows:** amber, with mid-arrow text labels in monospace
- **No** drop shadows, gradients, rounded corners, or icons
- Flat, mechanical, like a 1970s schematic
- Each diagram authored as a standalone `.svg` in
  `static/diagrams/how-it-works/`, inlined into the rendered HTML at
  build time so it inherits page CSS and adds no extra request

## Navigation and discoverability

- Add `/how-it-works` link to the site footer next to the existing
  "Made in San Francisco by @cbzehner" line.
- Add a small "How this works →" link below the spot grid on the home
  page. Subtle, not a banner.
- Sticky **right-rail** TOC at desktop widths listing the seven
  anchors, scrollspy-highlighted as the user scrolls. Collapses on
  mobile to a single "Jump to…" select. Right-rail (rather than left)
  visually distinguishes `/how-it-works` from the home page's
  left-column spot filters.

## Repo layout

- `content/how-it-works.md` — the prose, with TOML frontmatter pointing
  at a custom template.
- `templates/how-it-works.html` — page template extending `base.html`,
  renders prose + inlines the SVG diagrams + emits the TOC.
- `static/diagrams/how-it-works/*.svg` — the seven hero diagrams,
  hand-authored, named by anchor (`overview.svg`, `api.svg`, etc.).
- `static/js/scrollspy.js` — small (~30 lines) vanilla scrollspy that
  highlights the current TOC item. No dependencies.
- `static/main.css` — additions for `/how-it-works`-specific layout
  (TOC, section spacing, code-block styling, diagram container).

## Content sources

During the writing phase, content comes from:

- `/seance` to surface session history for: the SF Rec & Parks email
  thread, the per-field stale-flag refactor (commit `188d427`), the
  day-rollover bug context, the wrangler `[build]` hook fix
  (`bbfb982`), and any abandoned approaches worth mentioning.
- `git log` for the factual backbone of each section.
- `docs/spec.md`, `docs/design-concepts.md`, `docs/schedules.md` —
  existing internal docs to mine for architecture rationale.
- The repo itself for code excerpts (Worker entry point, KV read /
  write, cron handler, schedule-tools parser, Tera templates).

## Constraints

- **No client JS framework.** No Mermaid runtime, no charting library,
  no React/Vue. The whole point of the page is consistent with the
  site's "no framework" pitch.
- **No new build dependencies** unless required. Diagrams are
  hand-authored SVG; no diagram compilation step.
- **Page weight target:** under 100KB on the wire after gzip,
  including all seven inlined SVGs. Aspirational, not a hard cap.
- **Accessibility:** every SVG has a `<title>` and `<desc>` describing
  the diagram for screen readers. Code blocks have language tags. TOC
  is reachable by keyboard.

## Out of scope (future posts)

- Cost / billing post: "What it costs to run a real site on Cloudflare
  Workers + KV in 2026."
- Split-flap animation breakdown.
- Lazy-loading Leaflet write-up (folded into §2 as two sentences here).
- Premortem post: "Things that almost killed this project."

## Code-excerpt link format

Code excerpts link to a **specific commit SHA** on GitHub (not
`main`), so line numbers and content always match the prose. The page
includes a small footer note:

> Excerpts are pinned to commit `<sha>`. Browse the current source at
> github.com/cbzehner/swimfrancisco.

The pinned SHA is captured at the time the page is written and only
updated intentionally (e.g. when a section is rewritten to reflect a
significant code change).
