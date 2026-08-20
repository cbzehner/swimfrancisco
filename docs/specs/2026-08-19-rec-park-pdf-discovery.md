# Rec & Park PDF Discovery and Automated Seasonal Ingest

**Author:** TBD
**Date:** 2026-08-19
**Status:** Draft
**Audience:** Operators of the schedule extract/review pipeline

---

## Overview

SF Rec & Park mints a new DocumentCenter ID for each seasonal schedule PDF. Swimfrancisco pins that ID in `schedule-tools/src/schedules/registry.toml` as `pdf_url`. Extract (`fetch_pdf(slug, entry.pdf_url)` in `schedule-tools/src/schedules/pipeline.py`) only re-GETs the pinned URL. Old IDs keep returning HTTP 200 with the previous season's bytes, so the SHA cache reports Unchanged and the public board keeps the last reviewed `effective_end`.

On 2026-08-19 that combination left Rec & Park senior pools CLOSED / "Schedule ended" while fall and interim PDFs were already live at new IDs. Two independent failures stacked: the daily cron had been dead since 25 Jul because `SCHEDULES_BOT_TOKEN` was missing, and even a healthy run cannot discover a new ID.

This design adds Rec & Park PDF discovery as a library in `discover.py`. **One writer per process:** `schedules discover` (CI) or a single `discover_all` at the start of a local `extract --provider` writes `registry.toml`. Extract then fetches the working-tree `pdf_url`. Discovery GETs each Rec & Park `official_page_url`, parses the Documents table that is already in the HTML, classifies each `/DocumentCenter/View/<id>` link, and rewrites `pdf_url` only when exactly one session-grid PDF is safe to adopt. FLAG means "do not auto-write `pdf_url`." It does not mean "do not extract." If `pdf_url` already points at a classified `session_grid` (table or band, including a human `--adopt`), extract proceeds.

Extract, review, carry-forward, and the rolling `auto/schedules-extract` PR stay the publication path. Extract still never writes `content/spots/` session grids. Auto-merge requires a carried human attestation on every changed pool **and** no blocking discover flags. No workflow that stages `registry.toml` may merge without that second gate.

---

## Background & Motivation

### What broke on 2026-08-19

The public board showed Rec & Park senior pools as CLOSED / "Schedule ended". Summer `effective_end` values were 13 Aug (Garfield, Rossi) or 15 Aug (Balboa, Coffman, Hamilton, Mission, Sava). Rec & Park had already posted fall and interim PDFs at new DocumentCenter IDs. The registry still pinned summer IDs:

| Pool | Registry (summer) | Current official (2026-08-19) |
|---|---|---|
| Balboa | 29562 | 29797 interim 11–29 Aug |
| Coffman | 29563 | 29798 fall 18 Aug–12 Dec |
| Hamilton | 29599 | 29800 fall 18 Aug–12 Dec |
| Mission | 29566 | 29801 fall 18 Aug–17 Oct |
| MLK | 29578 | 29802 pt.1 18 Aug–26 Sep (29803 pt.2 exists, not always on the page) |
| Rossi | 29570 | 29804 fall 16 Aug–10 Dec |
| Sava | 29571 | 29815 Fall 1 Aug 18–28; Fall 2 is 29805 |
| Garfield | 29564 | table shows **29808 maintenance flyer**; fall grid **29799 is unlinked** |
| North Beach | 29778, `missing_current_schedule` | Cool 29778 + Warm 29779; content already runs through 29 Aug |

Verified live Documents-table rows (raw `httpx` HTML; markdown fetchers drop the cell):

- Hamilton: `Hamilton Pool _ Fall 2026 _ August 18 to December 12` → `/DocumentCenter/View/29800`
- Garfield: `Garfield Pool Maintenance Closure 8-14_9-7 2026` → `/DocumentCenter/View/29808`
- North Beach: Cool 29778 + Warm 29779 on one row
- Sava: `Sava_Pool_Fall12026_Aug18toDec26_` → `/DocumentCenter/View/29815`
- MLK: `MLK Pool_Fall2026_pt1_Aug 18_Sep26` → `/DocumentCenter/View/29802`

### Diagnosed failures

1. **Cron dead 25 Jul–19 Aug.** `SCHEDULES_BOT_TOKEN` has been required since `eec3511` (23 Jul). The secret did not exist until 2026-08-19T17:57Z. Every scheduled run failed at token preflight in ~8s; extract never started. Example: [run 32046054738](https://github.com/cbzehner/swimfrancisco/actions/runs/32046054738) on Monday 17 Aug. GitHub emails failed scheduled workflows; that did not surface a 25-day outage.

2. **Extract cannot discover new IDs.** `fetch_pdf(slug, entry.pdf_url)` only GETs `registry.toml`. Rec & Park mints a new ID each season; old IDs still 200 the summer PDF, so SHA is Unchanged. Today's successful dispatch ([run 32284853618](https://github.com/cbzehner/swimfrancisco/actions/runs/32284853618)) cache-hit 8 Rec & Park pools. PR #33 was Koret + 24 Hour Fitness only.

3. **Trust boundary still holds, and must keep holding.** Extract never writes `content/spots/`. `just schedules-review` is the only path that projects session grids. Auto-merge only when `pending-reviews` is empty (carried attestation). Discovery must not punch a hole through that boundary.

The workflow started weekly Monday (`0 16 * * MON`, `ca7091f`) and became daily (`0 16 * * *`, `8e587ca`). Leftover "Next Monday will produce another." copy remains in `pr_summary.py`, plus a false line that published pages are "running on an unverified projection." Extract does not write `content/spots/`; the live site stays on the last reviewed window until a reviewed PR merges.

### Why this is a workflow gap, not a model gap

Gemini and Anthropic extract whatever PDF `fetch_pdf` hands them. They never see the facility page. `official_page_url` is currently identity and report-only (`PoolEntry.official_page_url` is copied into results and reports). This design is the first consumer that fetches it.

---

## Goals & Non-Goals

### Goals

- Detect a new Rec & Park DocumentCenter ID from a raw `httpx` GET of `official_page_url`.
- Auto-adopt `pdf_url` only when exactly one session-grid PDF is safe (table wins; no second same-pool `session_grid` in the band).
- Extract the current pointer through today's Gemini path, write `data/<slug>/<date>-<sha12>/`, and refresh the existing rolling PR `auto/schedules-extract`. After a human `--adopt`, daily extract must fetch that pointer even if the table is still flyer-only.
- Stage `registry.toml` and `data/` on that same PR. A registry URL change is a meaningful diff even when `data/` is quiet.
- Keep the trust boundary: extract never writes `content/spots/` session grids; auto-merge only when every changed pool carried attestation **and** `discover-blocking` is empty. The second gate lands in the same PR that first stages `registry.toml`.
- Page on token preflight failure via a rolling GitHub issue that uses `github.token` from a job that cannot write contents or PRs. Preflight proves the PAT works, not merely that the secret is non-empty. PAT remains required for checkout and PRs.
- Drop daily Anthropic from CI. Gemini is fail-closed. Bakeoff stays local (`schedules debug bakeoff`) and does not write `registry.toml`.
- Give the operator an honest PR: old ID → new ID, filename, kind, pending slugs, and any same-pool PDF that is not on the table (Sava Fall 2). Delete leftover Monday copy and the unverified-projection line.
- Provide a human path that can project a closure-only payload (Garfield 14 Aug–7 Sep) without making a flyer the schedule URL.
- Cover classification with fixtures: one grid, two split grids, two non-split grids, flyer-only, flyer with weekday tokens, empty table, band after registry max jumps, `--adopt` then extract. Cover the workflow with contract tests.

### Non-goals

- Publishing any session grid, lane count, or access-hours change without `just schedules-review`.
- Split-PDF *extraction* (North Beach Cool + Warm). Still skip + flag + manual review.
- Auto-adopting among two overlapping windows (Sava Fall 1 vs Fall 2). Human `--adopt`s one.
- Auto-adopting a grid found only by the ID-band probe (Garfield 29799). Flag only; persist the ID until adopt or 404.
- Rolling `pdf_url` to a maintenance flyer.
- Dual URL history in TOML (`pdf_urls[]`). Git + `reviewed.json.source_pdf_url` is provenance.
- Playwright, CivicPlus DocumentCenter listing/API, sitemap, or RSS as the discover transport.
- A second rolling branch, a Slack bot, or a parallel "needs review" markdown file.
- Bumping `data/bulletin.json` on detect. `just release` after review still owns the bulletin.
- Semantic PDF identity ("same schedule, new bytes"). Byte SHA remains identity.
- Extending a summer `effective_end` because a fall PDF exists.
- Changing deploy. Merge to `main` still ships.
- Discovering non–Rec & Park sources (`bay-club-gateway` is not in scope).

---

## Key Decisions

These resolve the counsel disagreements and the four review discussion questions. Each is a cut-over, not a shim.

### 1. CLI shape: one library, one writer per process

**Decision.** New module `schedule-tools/src/schedules/discover.py` is the only classifier. **One process writes `registry.toml`.**

| Process | Writer | Extract |
|---|---|---|
| CI | `schedules discover` | `schedules extract --provider gemini --no-discover` (reads the working-tree registry; does not call `discover_all`) |
| Local `just schedules-extract --provider gemini` | `run_pipeline` calls `discover_all` **once** at the start | `_process_entry` never discovers |
| `schedules debug bakeoff` | none | `run_pipeline(..., apply_discover=False)` because `compare_with` is set. Uses the working-tree pins as-is. |
| `extract --url` | none | skips discover; does not rewrite the registry |

`--direct` never discovers. There is no process-level cache and no stamp file. `_process_entry` does not call discover. Local extract remains unable to hit a stale URL because *that process* writes first. CI extract is not a second writer.

`--no-discover` is the CI handoff, not a way to skip discovery as a product. Contract-test that the Gemini step includes `--no-discover` and that the discover step runs first.

**FLAG vs extract.** FLAG means "do not auto-write `pdf_url`." It does **not** mean "do not extract." `_process_entry` does not skip on FLAG. Extract fetches the current pointer whenever `source_status == "published"` (existing skip for `missing_current_schedule` / non-PDF `access_hours_only` is unchanged).

Set `missing_current_schedule` **only** for `split_part` (North Beach / MLK: one PDF is not the whole pool). For 2+ whole-pool `session_grid` windows (Sava Fall 1 + Fall 2), leave `source_status = published` and FLAG in notes only (`blocking=true`). Daily extract still GETs the current (summer) pointer as Unchanged until the operator `--adopt`s.

**`--adopt` then extract.** `--adopt` of a classified `session_grid` writes `pdf_url` **and** sets `source_status = published` so extract proceeds (Garfield 29799, Sava 29815). `--adopt` of a `split_part` writes `pdf_url` but must **not** auto-publish (Cool or Warm alone is not the pool). After `just schedules discover --adopt sava-pool=29815`, the next discover pass sees 29815 as a classified `session_grid` on a `published` entry → `unchanged` → extract GETs 29815. Same for Garfield 29799 while the table is still flyer-only.

### 2. Daily Anthropic: drop it

**Decision.** CI runs Gemini only. Remove the Anthropic step **and** `ANTHROPIC_API_KEY` from the job `env` in `.github/workflows/schedules-extract.yml`. Bakeoff stays local via `schedules debug bakeoff --provider gemini --compare-with anthropic`. `ANTHROPIC_API_KEY` remains a documented local secret, not a CI requirement.

**Rationale.** The user asked to simplify CI. Dual-provider CI doubles PDF spend and lets a Gemini failure hide behind `continue-on-error` while Koret/HTML still greens the job. The review queue seeds from Gemini first (`_PROVIDER_PREFERENCE = ("gemini", "anthropic")` in `review.py`). Anthropic remains available for disagreements; it does not need to run unattended every morning.

### 3. ID-band probe: one shared scan, FLAG only, persist candidates

**Decision.** Each discover pass runs **one** DocumentCenter band scan, shared by every Rec & Park pool, then filters hits by that pool's filename tokens.

```
max_id = max(view IDs parsed from every in-scope sfrecpark_pdf pdf_url)
           computed once before any rewrite
probe   = {max_id+1 … max_id+40} ∪ {persisted candidate IDs for any pool}
```

Persisted candidates are View IDs recorded on a previous blocking `discover:` notes line (`band_session_grid` and other `session_grid` ids). Re-GET them every pass even when they sit **below** the current `max_id`. Drop a persisted ID only when that GET is HTTP 404 or the ID has been adopted as that slug's `pdf_url`.

**Walk the whole forward window.** GET every ID in `max_id+1 … max_id+40`. Do **not** early-stop on consecutive 404s inside that window. Treat non-PDF HTTP 200 (JPEG, HTML interstitial) as "not a candidate" and keep walking. 40 × 200ms is ~8s on the daily job. Persist ∪ covers IDs **below** the next day's max (29799 after Rossi/Sava pins move up). The remaining miss is only an ID **more than 40 above** registry max.

**Never auto-adopt a band-only find.** Report it, persist it, re-GET it.

**Rationale.** This is how Garfield 29799 and Sava 29805 are found on the first pass while the table may show a flyer or only Fall 1. A 5-404 stop after 29779 (North Beach Warm) would skip 29780–29798 and never persist 29799/29805; Sava would then auto-adopt the only table grid (silent 10-day Fall 1). Walking the full 40 closes that hole. Persist then keeps 29799 after the registry max jumps. A per-pool 40-GET walk is unnecessary; N flyer-only pools share the one scan. Making the band the primary scanner would ingest JPEGs and other departments' files (29807 is a JPEG). Auto-adopting a file Rec & Park has not linked on the facility page is the wrong default.

### 4. Board pending-review chip: not in this slice (resolved A)

**Decision.** After `effective_end`, keep `POST_SEASON` / "Schedule ended DATE" until review projects. Do not invent a pending schedule in frontmatter. `pick_active_schedule` / `resolveScheduleForDate` keep seeing the last reviewed window. CI does not write a chip onto `main` before the review queue is finished. No `content/spots/` write from CI. No auto-merge exception for a flag-only notice.

**Rationale.** Product call closed 2026-08-19: option A. Extract does not write `content/spots/`. Auto-merge is gated on an empty review queue, so a chip on `main` before review would be a second publication path. The operator signal in this slice is the rolling PR (`needs-schedule-review` + `pending-reviews` + an honest lead). B and C remain rejected alternatives under Open Questions §1.

### 5. Closure notices: never the schedule URL; human path via `--url`

**Decision.** Discover never writes a flyer to `pdf_url`. A flyer is `closure_notice` and becomes a FLAG (no pointer write). The operator projects a closure-only payload (`schedule_basis = "temporarily_closed"`, empty `sessions`, non-empty `closures`) by extracting the flyer with an explicit override:

```
just schedules-extract --provider gemini --only garfield-pool --url https://sfrecpark.org/DocumentCenter/View/29808
```

`--url` is new. It fetches that URL into `data/<slug>/<date>-<sha12>/` and does **not** rewrite `registry.toml`. Review attests. `project` / `merge` appends a new `[[extra.schedules]]` window by `effective_start`. `pdf_url` stays on the last session-grid ID until a real grid is adopted.

CI never passes `--url`. Contract-test that the workflow YAML does not contain `--url`.

**Rationale.** Making 29808 the current pointer would replace a real grid URL with a flyer. The next discover pass would then have to "un-adopt" it. The existing schema already supports this payload (Sava's 2026-01-06 window; `test_validate_accepts_temporarily_closed_without_sessions_or_access_hours`). `sessions_dropped_to_zero` must stop being catastrophic when `schedule_basis == "temporarily_closed"`, or a local flyer extract against a pool that previously had sessions exits 1 for a valid payload (`validate.py` lines 35–40).

### 6. Auto-adopt is conservative; 2+ session-grid windows FLAG

**Decision.** Auto-adopt `pdf_url` if and only if all of the following hold:

1. Exactly one **table** link classifies as `session_grid`.
2. The shared band (plus persisted IDs) has **zero** additional `session_grid` hits for this pool. Two or more same-pool session-grid windows (table + band) → FLAG both and require `--adopt`. Do not silently take a 10-day interim.
3. View ID ≠ the current `pdf_url` ID.
4. Filename or anchor text matches this pool's tokens, not another pool's.
5. Not `split_part`, not `closure_notice`, not `other`.
6. `source_status == "published"` (North Beach stays skipped).

Then rewrite that slug's `pdf_url` only. Extract runs. Carry-forward still applies if the payload is byte-equal to the last human review.

When auto-adopting (or leaving `unchanged` on the same ID), attach any other same-pool band/table hits that are **not** `session_grid` (flyers, `other`) as **non-blocking** extra candidates on the PR lead. A `session_grid` ID must **never** appear on an `extra` line. Sibling session-grids belong on the blocking `flag` line until `--adopt`.

**If `pdf_url` already points at a classified `session_grid` (table or band, including a human `--adopt`):** action is `unchanged`, extract proceeds, do not revert the pointer. `source_status` must be `published` for extract to run; `--adopt` of a `session_grid` sets that.

**Flag, do not adopt:** 0 table grids; 2+ session-grid windows (table and/or band) — notes only, **leave `published`**; any `split_part` — set `missing_current_schedule`; grid found only by ID-band; notice/maintenance-only table. SHA identity is a fetch concern, not an adopt gate: if Rec & Park copies the same bytes to a new ID, we still roll the pointer so the next page comparison is current, then `fetch_pdf` cache-hits or carry-forward auto-merges.

**Sava 2026-08-19.** Table has 29815 (Fall 1). Band finds 29805 (Fall 2). That is 2+ session-grid windows → FLAG both in notes (`blocking=true`), `source_status` stays `published`, `pdf_url` stays 29571. Extract still GETs the summer pin (Unchanged). The PR lead names both IDs. Operator `--adopt`s 29815 or 29805, which sets `published` (already true) and the new `pdf_url`. No silent 10-day window on `content/spots/`. 29805 stays on the blocking `flag` line until that `--adopt`; it is never `extra`.

### 7. Token issue: prove the PAT; close on preflight success; isolate `github.token`

**Decision.** Preflight fails closed if the secret is empty **or** a cheap authenticated call with the PAT fails (`git ls-remote` of `cbzehner/swimfrancisco`). The rolling issue files on preflight failure and **closes when preflight succeeds**, not when the whole job is green. `github.token` lives only in jobs whose `permissions` are `{ issues: write }` and that do not checkout.

---

## Proposed Design

### Architecture

```mermaid
flowchart TD
  cron["Daily cron 0 16 * * * plus dispatch"] --> labels["Job ensure-labels: github.token issues write"]
  labels --> preflight["Job extract: PAT preflight empty plus ls-remote"]
  preflight -->|preflight fail| pageFail["Job page: file rolling issue"]
  preflight -->|preflight ok| checkout["Checkout with SCHEDULES_BOT_TOKEN"]
  checkout --> discoverCli["schedules discover writes registry"]
  discoverCli --> direct["extract --direct continue-on-error"]
  discoverCli --> gemini["extract --provider gemini --no-discover fail-closed"]
  gemini --> fetch["fetch_pdf of working-tree pdf_url"]
  fetch --> artifacts["data/slug/date-sha12/"]
  artifacts --> detect["git add data/ and registry.toml"]
  detect -->|meaningful| pr["Rolling PR auto/schedules-extract"]
  pr -->|pending-reviews empty AND discover-blocking empty| automerge["--auto squash"]
  pr -->|else| human["just schedules-review then merge"]
  human --> content["content/spots/ via project"]
  preflight -->|preflight ok| pageClose["Job page: close rolling issue"]
```

### Trust boundary

```mermaid
flowchart LR
  subgraph untrusted ["Untrusted"]
    page["official_page_url HTML"]
    pdf["DocumentCenter PDF"]
    llm["Gemini payload"]
  end
  subgraph reviewGate ["Human gate"]
    reviewed["reviewed.json"]
  end
  subgraph trusted ["Trusted / live"]
    spots["content/spots/*.md"]
    board["Public board"]
  end
  page --> discover["discover.py"]
  discover -->|"pdf_url only on adopt"| registry["registry.toml"]
  registry --> pdf
  pdf --> llm
  llm --> data["data/ artifacts"]
  data -->|"carry-forward if byte-equal"| reviewed
  data -->|"else pending-reviews"| review["schedules review"]
  review --> reviewed
  reviewed --> project["schedules project"]
  project --> spots
  spots --> board
```

Nothing to the right of `reviewed.json` is written by CI except a carried attestation of a payload a human already approved.

### Discovery algorithm

**Scope:** registry entries where `source_kind == "sfrecpark_pdf"` **and** `official_page_url` host is `sfrecpark.org` (case-insensitive). This is the nine Rec & Park pools. It excludes `bay-club-gateway`, which has no `source_kind` and therefore defaults to `sfrecpark_pdf` in `registry.py` (`registry.toml` lines 78–82) but lives on `www.bayclubs.com`. Do not GET Bay Club. Do not upsert `discover:` notes on a non–Rec & Park pool. A unit test asserts the selected slugs are exactly those nine.

Giving `bay-club-gateway` an explicit `source_kind` is a one-line follow-up, not required for this slice.

#### 1. Fetch the facility page

`GET entry.official_page_url` with the existing bot UA from `direct_sources/http.py`:

```
User-Agent: SwimFranciscoScheduleBot/0.1 (+https://swimfrancisco.com)
```

Follow redirects. Timeout 30s, 2 retries, same shape as `fetch_text`. Parse HTML, not Markdown. CivicPlus `/DocumentCenter` listing pages are JS-empty and are not consulted.

Lift the UA string into a shared constant (for example `schedules.http.BOT_USER_AGENT`) so discover and the direct fetchers do not drift. `fetch_pdf` currently sends no UA; leaving that alone is acceptable because DocumentCenter View URLs already 200 today. Discover *must* send the UA because this is the first fetch of the facility HTML.

#### 2. Parse only the Documents table

CivicPlus markup varies. The parser is not "the `th` row only."

From the `th` whose stripped text is `Documents`, collect `a[href*="/DocumentCenter/View/"]` that sit in:

- the same `tr` as that `th`, or
- a `td` sibling of that `th`, or
- subsequent `tr`s of the same `table`

Stop walking rows at the next `tr` that contains a `th`, or at the next heading (`h1`–`h4`) / section whose text is `Features` or `Facility and Deck Rules`.

Ignore every `/DocumentCenter/View/` link under the "Facility and Deck Rules" heading (deck-rules PDFs 19018–19020).

Use stdlib `html.parser.HTMLParser` (already used in `direct_sources/parsing.py`). Do not add BeautifulSoup.

```python
@dataclass(frozen=True)
class DocumentLink:
    view_id: int
    href: str          # absolute https://sfrecpark.org/DocumentCenter/View/<id>
    anchor_text: str   # e.g. "Hamilton Pool _ Fall 2026 _ August 18 to December 12"
```

`discover_facility_documents(html: str) -> list[DocumentLink]` returns those anchors. If the table is missing or has zero matching anchors, return `[]`.

Fixtures are reduced but **structurally honest** cuts of raw `httpx` HTML: a `th` Documents cell plus View anchors in the same `tr`/`td` and a following-`tr` variant, plus a deck-rules block that must be ignored.

#### 3. Classify each link

```python
CandidateKind = Literal["session_grid", "closure_notice", "split_part", "other"]

@dataclass(frozen=True)
class ClassifiedDocument:
    link: DocumentLink
    kind: CandidateKind
    filename: str | None
    source: Literal["table", "band", "persisted"]
```

Classification is deterministic and conservative. Inputs, in order:

1. Anchor text.
2. `Content-Disposition` filename from HEAD or GET of the View URL.
3. First-page text via existing `signals.extract_page_texts` / `_has_grid_header` (≥3 day tokens on one line) when (1)+(2) do not settle the kind, and as a **confirm** on a would-be auto-adopt of a `session_grid`. A grid header must **not** remove a closure classification.

Rules, applied in this order:

| Kind | Signals |
|---|---|
| `closure_notice` | Filename or title matches `maintenance`, `closure`, `closed`, `notice`, `repair`, or `attention`. **Wins even when page 1 has ≥3 day tokens.** Garfield 29808 titled `Garfield Pool Maintenance Closure 8-14_9-7 2026` stays a flyer if it lists Mon–Fri. |
| `split_part` | Cool/Warm, `pt.1` / `pt.2` / `part 1` / `part 2` as a **part token** (`pt.1`, `pt 1`, `part 1`), `Warm Pool`, `Cool Pool`. North Beach 29778/29779, MLK 29802. `Fall12026` / `Fall 1` is **not** `split_part` (Sava Fall 1 is a whole-pool window). |
| `session_grid` | Not the above; filename or title has this pool's tokens **and** a season/schedule token that is not only a date range: `schedule`, `fall`, `spring`, `summer`, `winter`, or `interim`. A date range alone (`8-14_9-7`, `Aug18toDec26` without `fall`/`schedule`/…) is not enough. First-page grid header confirms a would-be adopt; it does not promote a closure. |
| `other` | JPEG, ranking lists, zoo budgets, deck rules that leaked in, anything else. |

Pool-token table (filename/title must match this slug, not another):

| slug | tokens (any one) |
|---|---|
| `balboa-pool` | `Balboa` |
| `coffman-pool` | `Coffman` |
| `garfield-pool` | `Garfield` |
| `hamilton-pool` | `Hamilton` |
| `martin-luther-king-jr-pool` | `MLK`, `Martin Luther King` |
| `mission-community-pool` | `Mission` |
| `north-beach-pool` | `North Beach`, `NB Pool` |
| `rossi-pool` | `Rossi` |
| `sava-pool` | `Sava` |

A file that matches another pool's tokens is `other` for this slug.

#### 4. Bounded ID-band probe (one scan per pass)

Always run **once** per discover pass, not only when a table has zero `session_grid`, and not per pool.

1. Parse persisted candidate IDs from every in-scope pool's existing `notes` (`discover:` line: `band_session_grid id=N`, `extra` ids, flagged ids).
2. `max_id` = max View ID in in-scope `pdf_url`s, computed before rewrite.
3. GET **every** ID in `{max_id+1 … max_id+40} ∪ persisted`, in ascending order, with a **200ms** delay between requests. Do not early-stop on 404s inside the forward window. Shared scan: Garfield and Sava both see 29799 and 29805 from this one walk even if 29779 succeeds and 29780–29798 404.
4. Keep a response if it is a PDF. Classify using filename + first-page rules. Assign the hit to the pool whose tokens match; ignore if none or several.
5. Non-PDF 200 → not a candidate; keep walking.
6. HTTP 404 on a **persisted** ID → drop it from persist. HTTP 404 inside the forward window → keep walking; the bound **is** `max_id+40`.
7. Do not scan the global DocumentCenter index.

Band-only `session_grid` results are FLAG, never adopt. They are persisted on that pool's blocking `discover:` line.

On 2026-08-19, before rewrite, `max_id` is 29778 (North Beach). Window 29779–29818 covers the live fall cluster (29797–29815) including unlinked 29799 and Sava 29805. After the first pass auto-adopts (Rossi 29804 is the highest auto-adopt), `max_id` becomes 29804. 29799 is then **below** the window and survives only as a persisted candidate that is re-GETed. 29805 may still sit inside the next forward window (29805–29844) and is also persisted on Sava's flag line until `--adopt`.

#### 5. Choose a roll

```python
RollAction = Literal["adopt", "unchanged", "flag"]

@dataclass(frozen=True)
class DiscoverDecision:
    slug: str
    action: RollAction
    old_url: str
    new_url: str | None
    kind: CandidateKind | None
    reason: str
    candidates: tuple[ClassifiedDocument, ...]
    extra_candidates: tuple[ClassifiedDocument, ...]  # non-blocking PR-lead siblings
    blocking: bool  # True for flag; False for adopt/unchanged
```

`choose_roll(entry, classified) -> DiscoverDecision`. Evaluate **in this order**:

1. `source_status != "published"` → `flag` (North Beach / MLK after a `split_part` FLAG). Do not pick Cool vs Warm. Do not change `pdf_url`. (`--adopt` of a `session_grid` has already set `published`, so this rule does not trap Sava.)
2. Current `pdf_url` View ID is among classified `session_grid`s (table, band, or persisted) → `unchanged`. Extract proceeds. Attach other same-pool hits that are **not** `session_grid` as `extra_candidates` (non-blocking). A `session_grid` ID never goes on `extra`. **This is the `--adopt` survival rule.**
3. Two or more distinct `session_grid` IDs for this pool (table + band + persisted, not `split_part`) → `flag`. Do not adopt. `blocking=true`. **Leave `source_status = published`.** PR lead names every ID. Operator `--adopt`s one. **Sava Fall 1 + Fall 2.**
4. Any table `split_part` or two or more table schedule-class links that include `split_part` → `flag`. Set `missing_current_schedule` if it was `published`.
5. Exactly one table `session_grid`, no other `session_grid` in band/persisted, ID ≠ current → `adopt`. Extra non-grid same-pool hits go on `extra_candidates` (non-blocking).
6. Exactly one table `session_grid`, no other `session_grid`, ID == current → `unchanged`. Same extra-candidate rule.
7. Zero table `session_grid` and one or more band/persisted `session_grid` → `flag` (Garfield 29799). Never auto-adopt. Persist those IDs.
8. Table is notice-only and no session-grid anywhere → `flag`. Persist nothing new except the flyer as a note.
9. Zero DocumentCenter links → `flag` with reason `empty_table`. Do not clear `pdf_url`.
10. Per-pool HTTP/parse error → `flag` with reason `fetch_error`. Continue other pools.

#### 6. Rewrite the registry

`pdf_url` remains the single current pointer. No URL history in TOML.

`apply_discover_decision(path, decision)` is a **text-level** edit of that slug's `[[pool]]` block. Do not tomlkit-dump the file.

**Locate the block.** Find `slug = "<slug>"` (quotes required). The block starts at the preceding `[[pool]]` and ends at the next `[[pool]]` or EOF.

**Mutations:**

| Action | `pdf_url` | `source_status` | `notes` |
|---|---|---|---|
| `adopt` (auto, unique table `session_grid`) | replace the quoted URL | unchanged (`published`) | drop a blocking `discover: … flag …` line; upsert a non-blocking `discover: extra …` line only for **non-grid** `extra_candidates`; otherwise remove a leading `discover:` line |
| `unchanged` | unchanged | unchanged | same notes rule as auto-adopt |
| `flag` (`split_part`) | unchanged | set `missing_current_schedule` if it was `published` | upsert blocking `discover:` line listing every split ID |
| `flag` (2+ whole-pool `session_grid` windows) | unchanged | **leave `published`** | upsert blocking `discover:` line listing every `session_grid` ID (table + band + persisted). 29805 stays here until `--adopt`. Never move a `session_grid` to `extra`. |
| `flag` (notice / band-only / empty / error) | unchanged | unchanged | upsert blocking `discover:` line; **keep** previous `band_session_grid id=N` unless that ID 404'd this pass or was adopted |
| `--adopt` of a `session_grid` | replace with that View URL | **set `published`** | clear the blocking `discover:` line; optional `extra` only for remaining **non-grid** siblings |
| `--adopt` of a `split_part` | replace with that View URL | **do not** set `published` (leave `missing_current_schedule`) | clear or keep split flag as notes; extract still skips |

Never rewrite `official_page_url`. Discover never auto-promotes `missing_current_schedule` → `published`. Only `--adopt` of a classified `session_grid` does that (including a later North Beach combined PDF). `--adopt` of a `split_part` must not.

**Notes insertion (copy this):**

- If the block has no `notes` key: insert `notes = """…"""` immediately after `source_status` if that key exists, else immediately after `official_page_url`.
- If `notes` is a single-line `notes = "..."` and we need a `discover:` prefix or a second line: rewrite as a triple-quoted block:

  ```
  notes = """
  discover: 2026-08-19 flag closure_notice id=29808 band_session_grid id=29799

  <original notes text, unescaped>
  """
  ```

- If `notes` is already triple-quoted: replace the first non-empty line if it matches `^discover:`; else prepend `discover: …` plus a blank line. Leave human lines after the first blank line untouched (North Beach's split explanation).
- Machine line grammar (one line, parseable):

  ```
  discover: YYYY-MM-DD <adopt|flag|extra> [reason] [id=N:kind[:band|:table|:persisted] …]
  ```

  Example flag (Garfield): `discover: 2026-08-19 flag closure_notice id=29808:closure_notice:table band_session_grid id=29799:session_grid:band`

  Example flag (Sava, 2 windows — both stay on this line until `--adopt`): `discover: 2026-08-19 flag multiple_windows id=29815:session_grid:table id=29805:session_grid:band`

  Example extra (non-blocking, **non-grid only**): `discover: 2026-08-19 extra id=29808:closure_notice:table`

  A `session_grid` ID must never appear on an `extra` line. 29805 is Sava Fall 2; it lives on the blocking `flag` line, not `extra`.

- Upsert is **idempotent**: if the new machine line equals the existing one (ignore the date token), do not rewrite the file. A date-only change is not a meaningful registry diff.

Parse persisted IDs from the existing **flag** machine line **before** rewriting: any `id=<digits>` whose kind is `session_grid` and source is `band` or `persisted`. Do not persist from an `extra` line (`extra` is non-grid only).

Tests must rewrite the real North Beach block (existing single-line `notes`) and a no-notes pool (Hamilton) without breaking `load_registry`.

In-memory `PoolEntry` objects used for the rest of the **discover** process carry the new URL. Extract in CI reloads the registry from disk after the discover step (`load_registry()` as today). Local `run_pipeline` reloads after its single `discover_all`.

### Extract integration

`_process_entry` does **not** call discover. It fetches `entry.pdf_url` as today.

```python
# pipeline.py — run_pipeline, --provider only
if apply_discover:  # True for local extract --provider; False for --no-discover, --direct, bakeoff
    discover_all(selected)  # writes registry, tmp/discovery-*.md/json
    registry = load_registry()
    selected = select_registry_entries(registry, source_mode=source_mode, slugs=slugs)

# _process_entry: existing skip for source_status != published
# then fetch_pdf(entry.slug, entry.pdf_url)  — no discover_pool, no skip-on-flag
```

`apply_discover` is true only when `source_mode != "direct"` and `compare_with is None` and `--no-discover` was not passed.

`--force` still bypasses the hash skip and the reviewed-snapshot fast path; it does not bypass discovery on a local extract (discover still runs once up front). `--url` sets `apply_discover=False` for that process and fetches the override URL.

Discovery outcomes land on the extraction report as review notes **read from `tmp/discovery-decisions.json`** (written by whichever process was the writer):

- `url_rolled` — info, old ID → new ID, filename
- `discovery_flagged` — warning, reason + candidate IDs

Extend `ReviewNoteKind` in `models.py` with those two values. `run_pipeline` attaches them from the decisions file; it does not re-discover to produce them.

Hard error: if every in-scope Rec & Park page fails to fetch, `schedules discover` (and local `discover_all`) exits 1 after writing the report. Per-pool skip does not fail the command.

### Closure-only review path

Garfield 29808 is a facility-wide closure (14 Aug–7 Sep), not an empty grid.

1. Discover FLAGs. `pdf_url` stays 29564. Notes record `closure_notice 29808` and persist `band_session_grid 29799`.
2. Rolling PR opens because `registry.toml` notes changed. Auto-merge is blocked (`blocking=true`). Extract still GETs 29564 (summer SHA cache-hit). That is Unchanged; it does not invent a grid.
3. Operator chooses:
   - **Fall grid:** `just schedules discover --adopt garfield-pool=29799`, then `just schedules-extract --provider gemini --only garfield-pool`. Discover (local writer) sees 29799 as a classified `session_grid` → `unchanged`. Extract GETs 29799. Then `just schedules-review`.
   - **Closure window now:** `just schedules-extract --provider gemini --only garfield-pool --url https://sfrecpark.org/DocumentCenter/View/29808`. Reviewer attests `schedule_basis = "temporarily_closed"`, `sessions = []`, `closures = [{start: "2026-08-14", end: "2026-09-07", reason: "…"}]`. Save projects a new `[[extra.schedules]]` via existing match-by-`effective_start` merge. `pdf_url` is untouched.
4. After `--adopt`, later daily CI: table may still be flyer-only. Persisted/adopted 29799 is a classified `session_grid` → `unchanged` → extract proceeds. Notes lose the blocking flag (idempotent extra line only if siblings remain).

`validate()` today marks `sessions_dropped_to_zero` catastrophic whenever `prior_sessions_count` is non-zero and `sessions` is empty, with **no** exemption for `temporarily_closed`. `too_few_weekly_sessions` already exempts `temporarily_closed`. Align the catastrophic check:

```python
if (
    prior_sessions_count
    and len(sessions) == 0
    and schedule_basis != "temporarily_closed"
):
    # sessions_dropped_to_zero, catastrophic
```

`project()` already calls `validate(canonical)` without `prior_sessions_count`, so a hand-built closure payload can land today. The change is so a local `--url` extract of a flyer is a review candidate, not a red extract.

### Split PDFs and multi-window PDFs

**North Beach.** Two table `split_part` links. Discover FLAGs and keeps `source_status = missing_current_schedule`. Existing pipeline skip stays. Do not pick Cool vs Warm. `--adopt` of Cool or Warm (`split_part`) must not set `published`. A later combined whole-pool `session_grid` `--adopt` does set `published`. Split-PDF extraction is out of scope.

**MLK.** Table shows `pt.1` (29802). Classify as `split_part` (`pt.1` is a part token). FLAG 29802 and any band 29803. Set `missing_current_schedule`. Do not adopt. Extract skips until a human `--adopt`s a whole-pool `session_grid` (not `pt.1`).

**Sava.** Table shows one `session_grid` (29815 Fall 1). Shared band finds 29805 (Fall 2, filename `Sava` + `fall`). Two session-grid windows → FLAG both in notes, **leave `published`**, leave `pdf_url` at 29571. Extract still GETs the summer pin (Unchanged). PR lead names 29815 **and** 29805. Operator `--adopt sava-pool=29815` sets `pdf_url` and `published` (already true); extract then GETs 29815. `Fall12026` is not `split_part`. 29805 stays on the blocking `flag` line until that `--adopt`. If the table later links only one of them and the other 404s, the remaining one can auto-adopt.

**PDF posted before the old window ends.** If it is the unique session-grid, auto-adopt, extract, do not replace live content. Reviewer adds an upcoming schedule. The board keeps the current grid through `effective_end`. After review, `pick_active_schedule` can also show the next window once it starts. If a sibling season PDF exists in the band, FLAG both instead.

### CI workflow

Keep **one** daily workflow, cron `0 16 * * *` plus `workflow_dispatch`. Same concurrency group `schedules-extract`. **Three jobs.** Workflow-level `permissions` are **not** used for the default token's issue write. Each job sets its own:

```yaml
jobs:
  ensure-labels:
    permissions:
      issues: write
    # no contents, no pull-requests, no checkout
    steps:
      - name: Ensure review and pager labels
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh label create needs-schedule-review --force \
            --color B60205 --description "Schedule extract PR needs a human"
          gh label create schedules-extract-blocked --force \
            --color B60205 --description "schedules-extract did not run"

  extract:
    needs: ensure-labels
    permissions:
      contents: write
      pull-requests: write
    # no issues: write — this job's github.token cannot file issues
    outputs:
      preflight_outcome: ${{ steps.token-preflight.outcome }}
    steps:
      - name: Verify CI-capable publication token
        id: token-preflight
        env:
          SCHEDULES_BOT_TOKEN: ${{ secrets.SCHEDULES_BOT_TOKEN }}
        run: |
          set -euo pipefail
          if [ -z "${SCHEDULES_BOT_TOKEN}" ]; then
            echo "::error::SCHEDULES_BOT_TOKEN is empty."
            exit 1
          fi
          git ls-remote --exit-code \
            "https://x-access-token:${SCHEDULES_BOT_TOKEN}@github.com/cbzehner/swimfrancisco.git" \
            HEAD >/dev/null
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.SCHEDULES_BOT_TOKEN }}
      # setup, discover, extract --direct, extract --provider gemini --no-discover
      # … reports, eval, bulletin, detect, PR …

  page-schedules-extract:
    needs: extract
    if: always()
    permissions:
      issues: write
    # no checkout
    steps:
      - name: File schedules-extract blocked issue
        if: needs.extract.outputs.preflight_outcome == 'failure'
        env:
          GH_TOKEN: ${{ github.token }}
        run: # see Token failure must page
      - name: Close schedules-extract blocked issue
        if: needs.extract.outputs.preflight_outcome == 'success'
        env:
          GH_TOKEN: ${{ github.token }}
        run: # close open labeled issues by github-actions[bot]
```

A fork `workflow_dispatch` files/closes issues on the **fork**, not on `cbzehner/swimfrancisco`. Triggers stay `schedule` and `workflow_dispatch`. No `pull_request_target`.

Extract job step order after checkout:

1. **Discover Rec & Park PDF URLs** — `uv --project schedule-tools run schedules discover`. Fail-closed on command crash or all-pages-failed. Per-pool flags are not a hard error.
2. `extract --direct` — `continue-on-error: true` (HTML 403s must not block city PDFs).
3. `extract --provider gemini --no-discover` — **no** `continue-on-error`. Fail-closed.
4. No Anthropic step. No `ANTHROPIC_API_KEY` in `env`.
5. Publish reports + upload artifacts (`if: always()`).
6. Eval, bulletin, detect, PR — exact `if:` below.

Fail-closed vs continue-on-error:

| Step | Policy |
|---|---|
| Token preflight | Fail-closed. Empty secret **or** `git ls-remote` failure. No `GITHUB_TOKEN` fallback for checkout or PRs. |
| Discover hard error | Fail-closed after writing a report. |
| Discover per-pool flag | Record and continue. Extract still fetches `published` pointers. |
| Direct extract | Continue-on-error. |
| Gemini PDF extract | Fail-closed. Subsequent detect/PR use `if: always() && …` so artifacts are not stranded. |
| Eval | Continue-on-error (observational). |

**Exact `if:` after Gemini** (copy into the YAML; contract-test the strings):

| Step | `if:` |
|---|---|
| Publish extraction evidence | `always()` |
| Upload extraction reports | `always()` |
| Run eval | `always() && steps.token-preflight.outcome == 'success'` |
| Regenerate bulletin fingerprint | `always() && steps.token-preflight.outcome == 'success'` |
| Detect new or changed artifacts | `always() && steps.token-preflight.outcome == 'success'` |
| Open or update PR | `always() && steps.token-preflight.outcome == 'success' && steps.detect.outputs.changed == 'true'` |

A custom `if:` in Actions still implies `success()` unless `always()` / `failure()` is included. Omitting `always()` on Detect/PR after a red Gemini step strands the rolling PR — the failure mode this design is stopping.

Detect change:

```bash
git add data/ schedule-tools/src/schedules/registry.toml
if git diff --staged --quiet; then
  echo "changed=false"
elif git diff --staged --name-only | grep -q 'registry.toml'; then
  echo "changed=true"   # URL roll or discover flag notes
elif ! uv --project schedule-tools run schedules has-meaningful-staged-data-changes; then
  echo "changed=false"  # metadata-only data/
else
  echo "changed=true"
fi
```

Auto-merge **in this same extract job / same PR that first stages `registry.toml`:**

```bash
PENDING=$(uv --project schedule-tools run schedules pending-reviews)
BLOCKING=$(uv --project schedule-tools run schedules discover-blocking)
if [ -z "${PENDING}" ] && [ -z "${BLOCKING}" ]; then
  gh pr merge "${PR_NUMBER}" --auto --squash || echo "::notice::..."
else
  gh pr edit "${PR_NUMBER}" --add-label "needs-schedule-review"
fi
```

`ensure-labels` has already created `needs-schedule-review` (`gh label create --force`), so `add-label` does not fail on a missing label.

`schedules discover-blocking` prints one slug per line from `tmp/discovery-decisions.json` where `blocking` is true. Empty output means no flags. The discover CLI step writes that file; extract `--no-discover` does not overwrite it.

PR title stays `chore(schedules): auto-extract YYYY-MM-DD`. One rolling branch. Force-push from current HEAD with the staged tree. No second "registry-only" PR. Do not commit registry to `main` from the bot except through this PR.

**No workflow that stages `registry.toml` may merge without the `discover-blocking` gate.** That gate ships in PR 3 with the `git add` / detect change. PR 4 is copy and docs only.

### Token failure must page

The 25-day outage was an empty secret. The next one may be a 90-day PAT expiry. Preflight must fail both.

**Prove the PAT.** After the non-empty check, `git ls-remote --exit-code` of `https://x-access-token:${SCHEDULES_BOT_TOKEN}@github.com/cbzehner/swimfrancisco.git` `HEAD`. Do not echo the URL in logs (Actions will mask the secret; still redirect stdout). Do not use `gh api user` — a fine-grained PAT may not have a user endpoint. `ls-remote` proves Contents-level repo access, which is what checkout needs.

**File/comment** (`page-schedules-extract`, `GH_TOKEN: ${{ github.token }}`, no checkout):

- Title (exact): `schedules-extract blocked`
- Label (exact): `schedules-extract-blocked`
- Author filter: `github-actions[bot]`
- Body: run URL, empty-secret vs `ls-remote` failure, "extract did not run."
- Dedup:

  ```bash
  EXISTING=$(gh issue list --state open --label schedules-extract-blocked \
    --json number,title,author \
    --jq '.[] | select(.title=="schedules-extract blocked" and .author.login=="github-actions[bot]") | .number' \
    | head -1)
  if [ -n "${EXISTING}" ]; then
    gh issue comment "${EXISTING}" --body "…"
  else
    gh issue create --title "schedules-extract blocked" \
      --label schedules-extract-blocked --body "…"
  fi
  ```

- **Close** when `needs.extract.outputs.preflight_outcome == 'success'`, even if Gemini later failed. The issue means "extract did not run," not "Gemini is red." A red Gemini step is a different class (Actions email).

`github.token` / `secrets.GITHUB_TOKEN` appear only in `ensure-labels` and `page-schedules-extract`. Those jobs have no `actions/checkout`. Checkout and `GH_TOKEN` for `gh pr` stay `SCHEDULES_BOT_TOKEN`.

GitHub already emails failed scheduled workflows. That is not sufficient; it did not surface the July–August outage.

### PR body (`pr_summary.py`)

Inputs expand from `git diff --staged -- data/` to also include `schedule-tools/src/schedules/registry.toml` and `tmp/discovery-decisions.json` when present.

Lead:

- `N Rec & Park pools need human review` plus `~10 min × N` (already in `_REVIEW_MIN_PER_POOL`).
- Per pool one line: slug, old ID → new ID, filename (e.g. `Coffman Pool Fall 2026 Aug18_Dec12.pdf`), kind (`session_grid` / `closure_notice` / `split_pdfs` / `multiple_windows` / `band_flag`), extracted `effective_start`–`effective_end` when artifacts exist.
- **Must name same-pool PDFs that are not on the table.** If `candidates` or `extra_candidates` include an ID absent from the Documents table (Sava 29805, Garfield 29799), the lead lists it on that pool's line. A short interim must not auto-adopt in silence; when 2+ session-grid windows FLAG, the lead lists both.

Delete:

- "The published page is running on an unverified projection until that happens."
- "Their published pages run on unverified projections until that happens."
- "Skip this week → close the PR. Next Monday will produce another."

Replace the projection lie with: the live site stays on the last reviewed window until this PR merges. Replace the Monday leftover with: daily extract will refresh this PR; closing it without merging will reopen on the next run that still sees a diff against `main`.

Checklist:

```
- [ ] git fetch origin && git checkout auto/schedules-extract
- [ ] just schedules-review  (work the queue)
- [ ] just release           (bulletin only if reviewed payloads changed)
- [ ] commit content/spots, data, registry.toml
- [ ] merge this PR; do not open a second one
```

A registry-only / flag-only PR with empty `data/` still renders a lead ("Garfield: flyer 29808; band-flagged 29799") and does not claim "Nothing to review."

### Operator sequence (one sitting)

```
git fetch && git checkout auto/schedules-extract && git pull
just schedules-review          # work the queue; Save projects content
just release                   # bulletin only if reviewed payloads changed
git add content/spots data schedule-tools/src/schedules/registry.toml
git commit -m "review fall 2026 Rec & Park schedules"
# merge the same rolling PR
```

If the queue is empty, `schedules-review` prints `nothing to review`. Adopt a band-flagged or multi-window ID first when that is the work:

```
just schedules discover --adopt sava-pool=29815
just schedules-extract --provider gemini --only sava-pool
just schedules-review
```

`--adopt` of 29815 (a `session_grid`) writes `pdf_url` and `source_status = published`. The second command is a **local** extract, so it is the writer: `discover_all` runs once, `choose_roll` returns `unchanged` because 29815 is a classified `session_grid` on a published entry, extract GETs 29815. Same sitting for Garfield 29799. In CI the next day, `schedules discover` is the writer (same `unchanged`) and `extract --no-discover` GETs the adopted pointer. `--adopt` of a `split_part` (North Beach Cool) does not publish; extract still skips.

### What auto-merges vs what stays open

| Outcome | Merge |
|---|---|
| Cache-hit, no `data/` change, no registry change | No PR |
| New capture, payload identical to last human review (`carried_from`), no blocking flag | Auto-merge on green CI |
| New `pdf_url`, SHA identical (re-export at a new ID), carried attestation | Auto-merge (quiet pointer rollover) |
| Access-hours-only / metadata-only `data/` and no registry change | No PR |
| New PDF SHA, payload changed | Rolling PR, no auto-merge |
| Discover FLAG (split, flyer, band-only, 2+ session-grid windows, empty table) | Rolling PR, no auto-merge (`discover-blocking` non-empty) |
| Human `--adopt` of a band ID; next extract of that pointer | Extract runs; auto-merge only if payload carried |
| Extractor failed after an adopt | Red job; detect/PR still run via `if: always() && preflight success` |
| North Beach split | Skip extract (`missing_current_schedule`). Flag. Manual |

`pending-reviews` stays the payload gate. `discover-blocking` is the second gate. Non-empty either output means a human owns the branch. **Both gates exist in the first workflow that stages `registry.toml`.**

---

## API / Interface Changes

### New CLI

```
schedules discover [--only slug1,slug2] [--dry-run] [--adopt slug=id]
schedules discover-blocking
```

| Flag | Behavior |
|---|---|
| (default) | Fetch pages, shared band scan, classify, apply auto-adopts and flags to `registry.toml`, write `tmp/discovery-report.md` and `tmp/discovery-decisions.json`. Exit 1 only on hard error. |
| `--dry-run` | Report only. No registry write. |
| `--adopt slug=id` | Operator confirms a FLAG candidate (Garfield 29799, Sava 29815 or 29805). Rewrites that `pdf_url` to `https://sfrecpark.org/DocumentCenter/View/<id>`. If the ID classifies as `session_grid`, set `source_status = published`. If it classifies as `split_part`, do **not** set `published`. Clears the blocking `discover:` line. Does not extract. |
| `--only` | Same slug filter as extract. |

`discover-blocking` prints blocking slugs, one per line, from `tmp/discovery-decisions.json`. Empty stdout is the auto-merge "no flags" signal, matching `pending-reviews`.

### Extract additions

```
schedules extract --provider gemini [--no-discover] [--url <notice-or-grid-url>]
```

`--no-discover`:

- Sets `apply_discover=False`.
- CI Gemini step **must** pass it (discover already wrote).
- Local default is to discover once and write.

`--url`:

- Requires `--only` with exactly one slug.
- Incompatible with `--direct`.
- Sets `apply_discover=False`.
- Does not rewrite `registry.toml`.
- Writes `data/<slug>/<date>-<sha12>/` as usual.
- Proposed new flag; does not exist on `cli.py` today (`--only`, `--direct`, `--provider`, `--force` only).
- Workflow YAML must not contain `--url`.

`--force` is unchanged: re-fetch and bypass hash skip, not discovery.

### Library (`discover.py`)

```python
def discover_facility_documents(html: str) -> list[DocumentLink]: ...
def classify_pdf(link: DocumentLink, *, pool_slug: str, pdf_bytes: bytes | None, filename: str | None) -> ClassifiedDocument: ...
def choose_roll(entry: PoolEntry, classified: list[ClassifiedDocument]) -> DiscoverDecision: ...
def rewrite_registry_pdf_url(path: Path, slug: str, url: str) -> None: ...
def apply_discover_decision(path: Path, decision: DiscoverDecision) -> None: ...
def persisted_band_ids(notes: str | None) -> frozenset[int]: ...
def discover_all(entries: list[PoolEntry], *, dry_run: bool = False) -> list[DiscoverDecision]: ...
```

### Workflow contract (replace, do not dual-track)

`tests/test_schedule_workflow_contract.py` today asserts three extract steps including Anthropic, `continue-on-error: true` ≥ 3, and `github.token` absent. After this design it asserts:

- Job `ensure-labels` has `permissions: issues: write` and no `actions/checkout`
- Job `page-schedules-extract` has `permissions: issues: write`, `if: always()`, no `actions/checkout`
- Job `extract` does **not** grant `issues: write`
- `schedules discover` appears before `schedules extract --provider gemini --no-discover`
- `schedules extract --provider anthropic` does **not** appear
- `ANTHROPIC_API_KEY` does **not** appear in the workflow
- `--url` does **not** appear in the workflow
- `schedules extract --direct` still appears once, still before Gemini
- Gemini step has no `continue-on-error`
- `github.token` / `secrets.GITHUB_TOKEN` appear only in `ensure-labels` and `page-schedules-extract`
- Checkout and `GH_TOKEN` for `gh pr` still use `SCHEDULES_BOT_TOKEN`
- `git add` includes `schedule-tools/src/schedules/registry.toml`
- Detect `if:` is `always() && steps.token-preflight.outcome == 'success'`
- Open or update PR `if:` is `always() && steps.token-preflight.outcome == 'success' && steps.detect.outputs.changed == 'true'`
- Close-issue step keys on `needs.extract.outputs.preflight_outcome == 'success'`, not job `success()`
- File-issue step keys on `preflight_outcome == 'failure'`
- Preflight contains `git ls-remote`
- Auto-merge conjunction includes `schedules discover-blocking`
- `gh label create` `--force` for `needs-schedule-review` and `schedules-extract-blocked`

### `justfile`

No new recipe required. `just schedules discover …` already forwards through the catch-all `schedules *args` recipe.

---

## Data Model Changes

### `registry.toml`

No new fields. `pdf_url` stays the single current pointer. `official_page_url` stays the facility page. `source_status` remains `published` | `access_hours_only` | `missing_current_schedule`.

Machine-written notes use a single leading line (see Rewrite the registry). Human notes follow after a blank line. Provenance of prior URLs stays in git history and in `reviewed.json.source_pdf_url`.

Expected first-run writes (2026-08-19 snapshot, subject to live re-check). Registry max before rewrite is 29778, so the shared band sees 29799 and 29805:

| slug | action | new `pdf_url` | why |
|---|---|---|---|
| `balboa-pool` | adopt | `…/29797` | one table session-grid, no sibling session-grid |
| `coffman-pool` | adopt | `…/29798` | same |
| `hamilton-pool` | adopt | `…/29800` | same |
| `mission-community-pool` | adopt | `…/29801` | same |
| `rossi-pool` | adopt | `…/29804` | same |
| `sava-pool` | **flag** (notes only) | unchanged 29571 | table 29815 + band 29805 → 2+ windows; **stay `published`**; extract GETs 29571 Unchanged until `--adopt` |
| `martin-luther-king-jr-pool` | flag (`split_part` pt.1) | unchanged 29578 | set `missing_current_schedule`; extract skips |
| `garfield-pool` | flag (flyer + persist 29799) | unchanged 29564 | stay `published`; extract GETs 29564 Unchanged |
| `north-beach-pool` | flag (already missing) | unchanged 29778 | |
| `bay-club-gateway` | **not selected** | — | host is not `sfrecpark.org` |

### `content/spots/`

No schema change in this slice. Review still projects via `merge()` into `[[extra.schedules]]`. Closure-only payloads reuse `schedule_basis = "temporarily_closed"`.

No pending-review flag in frontmatter (Key Decision 4).

### Artifacts

| Path | Committed? | Role |
|---|---|---|
| `tmp/discovery-report.md` | no | Human-readable discover scorecard; appended to the Actions step summary |
| `tmp/discovery-decisions.json` | no | Machine gate for `discover-blocking` and `pr-summary` |
| `data/<slug>/<date>-<sha12>/` | yes (except `source.pdf`) | Existing extract artifacts |
| `schedule-tools/src/schedules/registry.toml` | yes | Staged on the rolling PR; `discover:` notes persist band IDs |

Bulletin is not bumped on detect.

### Validation

`sessions_dropped_to_zero` is not catastrophic when `schedule_basis == "temporarily_closed"`. Existing `test_validate.py` gains a case with `prior_sessions_count > 0`.

---

## Alternatives Considered

### A. CI-only `schedules discover`, extract stays pinned

CI brief's first shape. Discover rewrites the registry, then extract runs.

- **For:** Named Actions step. Extract code stays untouched.
- **Against:** `just schedules-extract --provider gemini` on a laptop still fetches last season's ID. That is the failure mode we are fixing. Rejected as the only call site.

### B. Discover folded into extract only; no CLI

Pipeline brief.

- **For:** Local extract cannot go stale. One command.
- **Against:** No `--dry-run`, no `--adopt`, no distinct CI failure. Operator cannot inspect Garfield 29799 without extracting. Rejected as the only call site.

**Chosen:** library + one writer per process (Decision 1). Not "three invocations, two writers."

### C. Keep daily Anthropic (Gemini then Anthropic)

Pipeline brief.

- **For:** Bakeoff data in CI. Reviewer can compare providers without a local run.
- **Against:** User asked to simplify CI. Dual `continue-on-error` hid Rec & Park failures behind Koret cache-hits. Review already prefers Gemini. Bakeoff stays local and does not write the registry.

### D. Newest DocumentCenter ID on the page wins

- **For:** Ten lines of code.
- **Against:** Garfield's newest linked ID is a maintenance flyer. North Beach would flip Cool vs Warm at random. Sava would need a human the moment Fall 2 is linked. Rejected.

### E. Playwright or CivicPlus listing as the transport

- **For:** Would survive a future JS-only Documents table.
- **Against:** Counsel verified the Documents table is in the raw HTML today. CivicPlus `/DocumentCenter` is JS-empty. Playwright is heavy for a daily cron. Revisit only if the HTML parse goes blind (see Risks).

### F. ID-band as primary scanner

- **For:** Finds unlinked grids (29799) without waiting for the table.
- **Against:** 29807 is a JPEG. Band without filenames ingests the wrong department's files. Bound of 40 is a guess. Kept as FLAG-only shared fallback plus persisted IDs.

### G. Write a pending-review chip to `main` before review

Ops question.

- **For:** After `effective_end`, swimmers would see "Rec & Park posted a fall schedule" instead of only "Schedule ended."
- **Against:** Requires extract (or a sibling step) to write `content/spots/` or another live file, and a merge path that bypasses `pending-reviews`. That is a second publication path. **Rejected 2026-08-19** (Open Question 1 resolved as A).

### H. Dual `pdf_url` / `pdf_urls[]` history in TOML

- **For:** In-file provenance.
- **Against:** Git and `reviewed.json.source_pdf_url` already record history. A second pointer invites extract to pick the wrong one.

### I. Skip extract on FLAG

Earlier draft. Kills `--adopt` then extract, and kills daily extract of a human-adopted pointer while the table is still a flyer.

- **Against:** FLAG is a write policy, not a fetch policy. Rejected.

### J. Auto-adopt Sava Fall 1 and only mention Fall 2 on the PR lead

Softer reading of "name the sibling."

- **Against:** A 10-day interim can land on `content/spots/` after review while the season PDF stays unchosen. FLAG both; require `--adopt`. Extra-candidate lines remain for non-grid siblings of a true single-grid adopt.

---

## Security & Privacy Considerations

- Facility pages and DocumentCenter PDFs are public. No new credentials.
- Bot UA identifies the client. Do not spoof a browser.
- `SCHEDULES_BOT_TOKEN` stays a fine-grained PAT: Contents + Pull requests read/write, repo-scoped, ≤90 day expiry. No fallback to `GITHUB_TOKEN` for publication. The 25-day outage is the worked example.
- `github.token` is used only in `ensure-labels` and `page-schedules-extract`, each with `permissions: { issues: write }` and no checkout. The extract job's default token cannot write issues; it does not need to. Still no `pull_request_target`. Forks cannot trigger this workflow on origin; a fork dispatch pages the fork.
- Discovery does not scrape the global DocumentCenter index. The band is one bounded walk plus persisted IDs, 200ms apart.
- Auto-adopt never publishes sessions. A misclassified PDF at most opens a PR with a review queue.
- `--url` is an operator override. CI does not pass it.
- Do not log full PAT values. Issue body records the run URL and whether the secret was empty vs `ls-remote` failed.

---

## Observability

Three signals. Each has a durable surface. Do not rely on the operator reading the Actions tab.

| Signal | Trigger | Surface |
|---|---|---|
| `cron_blocked` | Preflight fails (empty `SCHEDULES_BOT_TOKEN` or `git ls-remote` failure) | Rolling issue `schedules-extract blocked`, label `schedules-extract-blocked`, author `github-actions[bot]`, via `github.token`. Close on the next **preflight success**, not full job success. |
| `stale_pin` | Pinned URL still 200s old bytes, but the facility page has a different ID or a FLAG | Rolling PR even on SHA cache-hit, because `registry.toml` changed. Lead names the class and any off-table same-pool PDF. |
| `review_needed` | New SHA extracted, `reviewed.json` absent, or a blocking discover flag | Same PR. Label `needs-schedule-review`. `schedules pending-reviews` + `schedules discover-blocking` are the machine signals. |

Gemini fail-closed is a red Actions run (GitHub email). That is a different class from "extract did not run." Do not comment on the rolling issue for Gemini failure (Open Question 2: no).

Reports:

- `tmp/discovery-report.md` — per-pool action, old/new ID, kind, candidates, persisted IDs.
- `tmp/extraction-report-gemini.md` — existing extract scorecard plus `url_rolled` / `discovery_flagged` notes.
- Actions step summary concatenates both (`if: always()`).
- Artifact `schedule-extraction-reports` also uploads `tmp/discovery-report.md`.

Quiet cache-hit weeks with no registry change produce no PR and no issue. That is the success case.

---

## Rollout Plan

No feature flag. Cut over.

Landing prerequisite for PR 3: `ensure-labels` creates the two labels on first run (`gh label create --force`). No hand step after PR 4.

1. Land PRs 1–2 (library + extract wiring) behind tests. Local `just schedules discover --dry-run` against live pages is the first smoke. Expected 2026-08-19 result: five adopts, four flags (Sava 2-window, Garfield, MLK, North Beach).
2. Land PR 3 (workflow + `discover-blocking` auto-merge gate). Watch the next daily run. Confirm: no Anthropic step, discover before Gemini `--no-discover`, issue does not open on a good PAT, issue closes if a leftover blocked-issue exists, registry + data staged, FLAG notes do not auto-merge.
3. Land PR 4 (PR copy, docs).
4. Operator works the first seasonal PR: review the five fall grids, `--adopt` Sava and Garfield (or `--url` Garfield closure), leave North Beach skipped.
5. Rotate `SCHEDULES_BOT_TOKEN` on its 90-day cadence. Preflight `ls-remote` + the rolling issue is the alarm if that rotation is missed.

### Rollback

- Revert the workflow to drop the discover step and restore Anthropic if Gemini-only is the problem. Registry pins stay wherever they were committed.
- Revert `discover.py` call sites; extract falls back to pinned URLs. Old IDs still 200.
- Do not revert a reviewed `content/spots/` projection unless the attested grid was wrong; that is a content fix, not a workflow rollback.

### First-run load

- 9 Rec & Park HTML GETs (not 10; Bay Club is out of scope), ~9–18 PDF HEAD/GETs for table links, **one** band of exactly 40 forward GETs + persisted IDs, 200ms apart (~8s for the window). Serial. Not 40 × N.
- 5 new Gemini extractions the first morning (the five adopts), plus Unchanged fetches of flagged **`published`** summer pins (Garfield, Sava). MLK is `split_part` → `missing_current_schedule` → extract skips. Then cache-hits until the next season or an `--adopt`.
- CI PDF spend drops by about half (no daily Anthropic).

---

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Facility HTML changes; Documents table disappears or is JS-only | High | Hard-fail discover after writing a report. Old `pdf_url`s keep working. Rolling issue / red X pages. Revisit Playwright only then. |
| Rec & Park serves the new season from the old View URL | Low | SHA skip still works. Pointer is wrong-but-functional until the next real ID mint. |
| Misclassified notice vs schedule; auto-adopt a flyer | High | Closure tokens win even with a page-1 day header. `session_grid` requires a season/schedule token, not only a date range. Worst case after that is a review PR. Next pass cannot `unchanged` a flyer pointer because a flyer is not a `session_grid`. |
| Band probe adopts the wrong department's PDF | High | Band is FLAG only. Filename must match this pool. |
| Forward band misses an ID **below** the new registry max (Garfield 29799 after Rossi 29804) | High | Persist `band_session_grid` IDs; re-GET them every pass; drop only on 404 or adopt. Test: after max is 29804+, Garfield still reports 29799. |
| ID more than 40 above registry max | Medium | Accept. First pass walks the full `max_id+1…+40` with no 404 early-stop, so 29799/29805 are in range today (max 29778 → 29818). An ID at max+41 is a FLAG/stale_pin for the operator to `--adopt` by hand. |
| Daily notes upsert forgets 29799 | High | Upsert merges persisted band IDs; does not replace them with flyer-only. |
| `SCHEDULES_BOT_TOKEN` expires (~90 days) | High | Preflight `git ls-remote` fails the same gate as an empty secret. Rolling issue via isolated `github.token`. Close on preflight success so a later Gemini red does not leave a lying "did not run" issue. |
| Gemini fail-closed strands artifacts | Medium | Detect `if: always() && steps.token-preflight.outcome == 'success'`. PR `if:` adds `&& steps.detect.outputs.changed == 'true'`. Contract-tested. |
| FLAG registry writes auto-merge before the second gate | High | `discover-blocking` ships in PR 3 with `git add` of `registry.toml`. No workflow that stages the registry may merge without it. |
| Operator closes the FLAG PR without merging | Low | Next day's checkout is `main`; discover writes the same notes; diff reappears; PR reopens. |
| `sessions_dropped_to_zero` blocks closure review | Medium | Exempt `temporarily_closed`. CI never extracts flyers. |
| Two writers in one CI job | Medium | CI extract passes `--no-discover`. `_process_entry` never discovers. Bakeoff does not write. |
| Registry text edit corrupts TOML | Medium | Specified insert point, quoting, North Beach + Hamilton rewrite tests, `load_registry` round-trip. |
| Rossi `official_page_url` uses mixed-case `/Facilities/Facility/Details/` | Low | GET the registry value as written; follow redirects. |
| Fine-grained PAT cannot create labels | Low | Label create uses `github.token` in `ensure-labels` (`issues: write`), not the PAT. |

---

## Open Questions

### 1. May the live board show "official schedule posted, not yet reviewed"?

**Resolved (2026-08-19): A.** After `effective_end`, keep `POST_SEASON` / "Schedule ended DATE" until review projects. Operator sees the rolling PR. No `content/spots/` write from CI. Do not ship a pending-review board chip in this slice. Do not invent an auto-merge exception.

Rejected alternatives (kept for rationale):

- **B.** CI writes a non-grid notice (source status / pending-review flag) onto the rolling PR, and we invent an auto-merge exception that lands *only that flag* on `main` while session grids wait. Honest for swimmers; second publication path.
- **C.** Board reads pending-review from a committed `data/` file that auto-merges even when `pending-reviews` is non-empty. Same exception, different file.

A later spec may reopen B or C. Until then: never render unreviewed sessions, even as "provisional."

### 2. Should a Gemini extract failure comment on the rolling `schedules-extract blocked` issue?

Preflight is the 25-day silent class. A red Gemini step already emails. Commenting would page the same issue for a different failure class. **No.** The issue means "extract did not run." It closes on preflight success even if Gemini is red.

### 3. Should `fetch_pdf` send the bot UA?

Out of scope. DocumentCenter View already 200s. Change it only if Rec & Park starts 403ing PDF fetches.

---

## Testing

### `tests/test_discover.py`

HTML fixtures (committed under `tests/fixtures/discover/`). Use reduced but structurally honest `httpx` cuts: `th` Documents + View anchors in the same `tr`/`td`, a following-`tr` variant, and a deck-rules block that must not be collected.

| Fixture | Source | Expect |
|---|---|---|
| `hamilton-one-grid.html` | Documents row with 29800 | one `session_grid`, `adopt` if registry is 29599 |
| `north-beach-two-grids.html` | 29778 + 29779 | two `split_part`, `flag`, no URL write |
| `sava-two-session-grids.html` | table 29815 + band 29805 | two `session_grid`, `flag`, `source_status` stays `published`, no auto-adopt, lead names both, 29805 on `flag` not `extra` |
| `garfield-flyer-only.html` | 29808 | `closure_notice`, `flag`, `pdf_url` unchanged |
| `garfield-flyer-with-weekdays.html` | 29808-class title + page-1 Mon–Fri | `closure_notice`, no adopt |
| `empty-table.html` | `<th>Documents</th>` and no View links | `flag`, `pdf_url` unchanged |

`classify_pdf`: grid vs flyer vs JPEG vs `pt.1` vs `Fall12026` (must **not** be `split_part`).

`choose_roll`: adopt; no-op same ID; flag split **and set `missing_current_schedule`**; flag 2+ session-grid windows **and leave `published`**; flag band-only; `unchanged` + extract when `pdf_url` already points at a classified `session_grid` (table or band) on a `published` entry; do not extract when `source_status != "published"`.

`rewrite_registry_pdf_url` / `apply_discover_decision`: Hamilton (no `notes`) adopt inserts `notes` after `official_page_url`; North Beach existing single-line `notes` becomes a triple-quoted block with `discover:` prepended and the split sentence preserved; neighbors intact; `load_registry` still parses.

Band: walk the entire `max_id+1…+40` window; **no** 404 early-stop. Test: after a success at 29779 and five 404s, GET 29799 and 29805 still happens on an **empty persist set**. Non-PDF 200 is not a candidate; keep walking. A filename-matching PDF is attached as a FLAG candidate, not adopted.

**Persist after max jump:** fixture registry with Sava `pdf_url` 29815 and Garfield notes `band_session_grid id=29799`. Shared forward window is 29816–29855. Mock GET 29799 → still a Garfield session-grid PDF. Expect Garfield FLAG still lists 29799.

**Selection:** `discover_all` / slug selection equals the nine Rec & Park pools. `bay-club-gateway` is absent.

### Pipeline / CLI

- Mocked table with a new ID → local extract's `discover_all` then `fetch_pdf` is called with the new URL.
- Same ID → Unchanged shortcut still holds.
- `--direct` never calls discover (monkeypatch a sentinel).
- `--no-discover` never calls `discover_all`; `fetch_pdf` uses the working-tree URL.
- `--url` skips discover, does not touch `registry.toml`, fetches the override.
- `--force` still discovers once up front on a local `--provider` run.
- **`--adopt` then extract (Garfield):** registry `pdf_url` is 29799, table fixture is flyer-only, 29799 is a classified band/persisted `session_grid` → `choose_roll` is `unchanged` → `fetch_pdf(..., 29799)` is called. Not `Skipped`.
- **Sava FLAG then `--adopt 29815` then extract:** 2-window FLAG leaves `published` and `pdf_url` 29571. `--adopt sava-pool=29815` sets `pdf_url` and `published`. Next extract `fetch_pdf(..., 29815)`, not `Skipped`. `--adopt` of a `split_part` does not publish.
- Bakeoff (`compare_with` set) does not write `registry.toml`.

### Workflow contract

See Interface. Also assert the Anthropic report path is gone from the summary loop, `tmp/discovery-report.md` is uploaded, and `--url` is absent.

### Validation

`temporarily_closed` + empty sessions + `prior_sessions_count > 0` is not catastrophic.

### Board

No board tests in this slice. Open Question 1 is resolved as A: no pending-review chip. Do not extend `tests/js/board-status.test.mjs` for a chip unless a later spec reopens B or C.

---

## Limitations (known, acknowledged)

- Discover is Rec & Park Documents-table HTML. If CivicPlus starts rendering that cell in JS only, discover goes blind until we add a different transport.
- A forward-only 40-wide probe will not find an unlinked ID *more than 40 above* registry max, or *below* other pools' new pins if that ID was never persisted. First run walks the full window from today's max (29778 → 29818) with no 404 early-stop, which is what records 29799 and 29805.
- Filename tokens are a hand list of nine slugs. A rename on Rec & Park's side ("MLK Jr Pool" → something else) FLAGs instead of adopting.
- North Beach stays manual until a separate split-PDF extract design.
- The live board will keep saying "Schedule ended" after `effective_end` until a human reviews, even if discover has already opened the PR.
- `official_page_url` 403/5xx on one pool FLAGs that pool; it does not fail the job unless every in-scope pool fails.
- `bay-club-gateway` still defaults to `sfrecpark_pdf` in `load_registry`. Discover ignores it by host. An explicit `source_kind` is a separate one-line cleanup.

---

## References

- Operator manual: `docs/schedules.md` (update in PR 4)
- Workflow: `.github/workflows/schedules-extract.yml`
- Extract/review: `schedule-tools/src/schedules/{cli,pipeline,fetch,registry,pr_summary,models,signals,review,project,merge}.py`
- Bot UA: `schedule-tools/src/schedules/direct_sources/http.py`
- Registry: `schedule-tools/src/schedules/registry.toml`
- Workflow contract: `tests/test_schedule_workflow_contract.py`
- Board POST_SEASON: `static/js/helpers/board.mjs` (`derivedClosures`, `computeDetailStatus`); predicate twins in `merge.pick_active_schedule` and `templates/spots/page.html`
- Closure schema: `docs/schedules.md` § Closure Contract (v2); `schedule_basis = "temporarily_closed"` already used by Sava
- Counsel briefs (2026-08-19): CI lane, pipeline lane, ops lane
- Triggering incident: cron dead 25 Jul–19 Aug; dispatch 32284853618 cache-hit Rec & Park; PR #33 Koret + 24 Hour Fitness only

---

## PR Plan

Each PR is independently reviewable and mergeable. Later PRs depend on earlier ones as noted. No board-chip PR in this slice (Open Question 1 resolved as A). **Do not start PR 3 until Issues 1, 2, 4, 5, and 6 have the written rules in this document** (they do, after this revision).

### PR 1 — Rec & Park discover library

**Title:** `feat(schedules): discover Rec & Park DocumentCenter IDs`

**Depends on:** none

**Files:**

- `schedule-tools/src/schedules/discover.py` (new)
- `schedule-tools/src/schedules/cli.py` (`discover`, `discover-blocking`)
- `schedule-tools/src/schedules/direct_sources/http.py` (lift UA constant; discover imports it)
- `tests/test_discover.py`
- `tests/fixtures/discover/*.html` (structurally honest `httpx` cuts)

**Changes:** Parse Documents tables (same `tr`/`td` and following-`tr`; ignore deck rules). Classify links (closure tokens win; `Fall12026` is not `split_part`). Shared band scan of the full `max_id+1…+40` window (no 404 early-stop) + persist ∪. `choose_roll` including `unchanged` when `pdf_url` is already a session-grid; FLAG 2+ windows **without** unpublishing; `split_part` sets `missing_current_schedule`. `--adopt` of `session_grid` sets `published`; `--adopt` of `split_part` does not. Surgical registry rewrite with specified insert/quoting. `--dry-run`. Selection excludes Bay Club. No pipeline or workflow wiring. `just schedules discover --dry-run` works against live pages.

### PR 2 — Extract calls discover once; `--adopt` then extract works; closure extract is valid

**Title:** `feat(schedules): roll pdf_url before Rec & Park extract`

**Depends on:** PR 1

**Files:**

- `schedule-tools/src/schedules/pipeline.py`
- `schedule-tools/src/schedules/cli.py` (`extract --url`, `extract --no-discover`)
- `schedule-tools/src/schedules/models.py` (`url_rolled`, `discovery_flagged`)
- `schedule-tools/src/schedules/report.py` (render those notes from `tmp/discovery-decisions.json`)
- `schedule-tools/src/schedules/validate.py` (`temporarily_closed` exemption)
- `tests/test_pipeline.py`, `tests/test_cli_extract.py`, `tests/test_validate.py`, `tests/test_extract_skip.py`

**Changes:** Local `--provider` calls `discover_all` **once** at the start of `run_pipeline`. `_process_entry` never discovers and never skips on FLAG. `--no-discover` reads the working tree. `--direct` and bakeoff do not write the registry. `--url` fetches without rewriting the registry. `--adopt` then extract fetches the adopted URL (Garfield flyer-only table; Sava FLAG then `--adopt 29815`). A closure-only payload against a pool that previously had sessions is not catastrophic.

### PR 3 — Daily CI: discover, Gemini-only, page on dead token, second auto-merge gate

**Title:** `ci(schedules): discover before Gemini and page token failure`

**Depends on:** PR 2

**Files:**

- `.github/workflows/schedules-extract.yml`
- `tests/test_schedule_workflow_contract.py`
- `schedule-tools/src/schedules/cli.py` (`discover-blocking` if not already in PR 1)

**Changes:** Three jobs (`ensure-labels`, `extract`, `page-schedules-extract`). Discover step; Gemini `--no-discover` fail-closed; drop Anthropic step **and** `ANTHROPIC_API_KEY`; preflight empty + `git ls-remote`; issue file/close isolated to `github.token` + `issues: write` + no checkout; close on preflight success; `git add` registry + `data/`; detect/PR `if:` strings as specified; `discover-blocking` conjunction on auto-merge; `gh label create --force`; upload `tmp/discovery-report.md`. **No workflow that stages `registry.toml` without this gate.**

Copy review can wait. This gate cannot.

### PR 4 — Honest PR body, operator manual

**Title:** `fix(schedules): name off-table siblings and drop leftover Monday copy`

**Depends on:** PR 3

**Files:**

- `schedule-tools/src/schedules/pr_summary.py`
- `tests/` for pr-summary (new or extend existing)
- `docs/schedules.md`

**Changes:** PR lead lists old ID → new ID, filename, kind, **and off-table same-pool PDFs**. Delete "unverified projection" and "Next Monday will produce another." Rewrite `docs/schedules.md` Registry Maintenance, Auto-extract, and delete the 2026-05-04 Current Blockers (Mission spring / Sava closed). Document: CI discovers; humans review payloads, split/notice/2-window cases, and `--adopt` / `--url`. Detect/auto-merge logic is already in PR 3.

A pending-review board chip is **out of scope** unless a later spec reopens Open Question 1 (B or C). This slice does not add a fifth PR for it.
