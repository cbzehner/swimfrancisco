+++
title = "How it works"
description = "What Swim Francisco is, why it exists, and how the data path works — pool PDFs through an LLM, NOAA hourly, all on one Cloudflare Worker."
template = "how-it-works.html"
insert_anchor_links = "left"

[extra]
commit_sha = "16e93a9"
github_repo = "https://github.com/cbzehner/swimfrancisco"
+++

## What Swim Francisco is

A status board for the fourteen places to swim in San Francisco —
nine public pools and five open-water spots — on one page. Every
spot shows whether it's open right now and, for the bay and ocean
spots, the current water temperature and the next tide.

## Why it exists

The information already exists, just not in one place.

SF Rec & Park publishes pool schedules as PDFs on sfrecpark.org —
calendar grids, formatted differently per pool, no machine-readable
feed. NOAA publishes bay and ocean water temperatures, but on
different endpoints than tides, and the tide station for ocean spots
isn't the same as the temperature station for the bay. Anyone
wanting a quick "is Hamilton open right now?" or "what's the bay at
Aquatic Park today?" answer has to assemble three or four sources by
hand and re-do it every time the schedule rolls.

Swim Francisco assembles them once, refreshes data hourly, rebuilds
the page when the calendar day rolls over, and serves the result as
a static site. There's no app, no account, no ads, no tracking. The
intended audience is the people who built it: city swimmers checking
the board before heading out.

## How it works at a high level

Three pipelines feed one static site.

1. **Pool schedules** come from PDFs on sfrecpark.org. Each PDF goes
   through an LLM that returns structured JSON. A human reviews
   every extraction against the source PDF before it lands. The
   approved result becomes frontmatter on a markdown file.

2. **Open-water conditions** come from NOAA water-temperature and
   tide-prediction endpoints, plus an NDBC buoy for ocean
   temperature. A Cloudflare Worker cron fetches them every hour,
   tolerates upstream failures with last-good fallbacks, and writes
   one slug-keyed JSON record to KV.

3. **The site itself** is a static build by Zola. Every push to
   `main` triggers a fresh build through Cloudflare Workers Builds.
   A separate cron tick at 00:00 PT triggers another build daily, so
   date-sensitive HTML (like "today is Thursday" on pool detail
   pages) stays current.

{{ diagram(name="overview", caption="Build, request, cron — three paths through one Worker.") }}

The browser loads static HTML, computes pool status from schedule
data embedded in the page, and fetches `/api/conditions` once to
hydrate live water temperatures and tides on the open-water rows.
Most of those fetches never reach the origin: the response is cached
at the Cloudflare edge for fifteen minutes, and the browser caches
it for the same window.

The rest of the page walks each pipeline in turn, then covers the
serving infrastructure, what it costs, and a few tidbits.

## Reading the PDFs

SF Rec & Park doesn't publish pool schedules as data. They publish
PDFs: calendar grids with program labels and time ranges in cells,
formatted differently per pool.

A regex parser was the first attempt. It was too brittle for the
layout. `pypdf` extracts the program label and the time range on
different lines, with cells from other days interleaved. A regex
strict enough to be correct missed half the rows; a regex loose
enough to catch them all matched garbage.

The current pipeline hands each PDF to an LLM (Anthropic or Gemini,
with a bakeoff mode) and asks for structured JSON. Because LLM
output is too variable to land in `content/spots/*.md` directly,
every extraction is reviewed by hand. Three checks frame what the
reviewer sees, and a fourth gate refuses outright when validation
catches an obvious failure.

{{ diagram(name="pdf-extraction", caption="Reviewed-lock SHA match fast-paths to content. Otherwise LLM → grounding → validation; catastrophic refusal exits non-zero, everything else awaits human review before content/spots is touched.") }}

**1. SHA-keyed cache.** Each fetched PDF gets a SHA-256. A matching
SHA reuses the existing review directory; a mismatch triggers a
fresh extraction. "Did the PDF change?" becomes hash equality.

**2. Grounding (advisory).** Every extracted session must come with
an evidence string. The grounding step normalizes the PDF text and
checks that the evidence's significant tokens appear *in order*
within a 250-character window:

```python
# schedule-tools/src/schedules/grounding.py
def _evidence_locally_grounded(evidence: str, pdf_text: str) -> bool:
    if evidence in pdf_text:
        return True
    e_tokens = _TOKEN_RE.findall(evidence)
    if not e_tokens:
        return False
    first_token = e_tokens[0]
    for match in re.finditer(re.escape(first_token), pdf_text):
        win_start = match.start()
        win_end = min(len(pdf_text), win_start + _EVIDENCE_WINDOW_CHARS)
        cursor = match.end()
        ok = True
        for tok in e_tokens[1:]:
            i = pdf_text.find(tok, cursor, win_end)
            if i == -1:
                ok = False
                break
            cursor = i + len(tok)
        if ok:
            return True
    return False
```

A literal substring check fails on calendar PDFs because the tokens
don't print contiguous. The window-and-order check tolerates the
layout but still rejects answers the model paraphrased. Coverage
shows up as a percentage in the review report so the reviewer knows
which sessions to scrutinize. It doesn't block the extraction from
becoming a review candidate.

**3. Validation gate (catastrophic only).** This is the one
automated step that actually refuses an extraction:

```python
# schedule-tools/src/schedules/validate.py
if prior_sessions_count and len(sessions) == 0:
    violations.append(Violation(
        code="sessions_dropped_to_zero",
        message="sessions_count dropped to 0 from a previously non-zero state",
    ))
    catastrophic = True
```

If a pool had thirty drop-in sessions yesterday and the LLM extracts
zero today, the run exits non-zero. The PDF probably changed in a
way the prompt doesn't handle yet; better to surface that as a hard
failure than as an empty review queue entry that might get
rubber-stamped.

**4. Human review.** Anything that survives catastrophic validation
lands as a review candidate — provider artifacts under
`data/<slug>/<date>-<sha12>/` plus a markdown report. The operator
runs `schedules review`, which opens the source PDF and a draft
`reviewed.json` in their editor side by side. On save,
`finalize_draft` rejects the draft if it's byte-identical to the
provider's payload (no review actually happened) and otherwise
projects the approved payload into `content/spots/<slug>.md` and
writes the `reviewed.json` keyed to the PDF's SHA. Future runs
short-circuit until the PDF changes:

```python
# schedule-tools/src/schedules/pipeline.py
if not force and not compare_with and reviewed_file.exists():
    return _build_unchanged(entry, fetch_result, reviewed_file)
```

The whole pipeline is offline tooling. It runs from a developer
machine or, weekly, from a GitHub Action that opens a PR with any
new PDFs surfaced for review. The Cloudflare Worker that serves the
site never executes any of this.

## Static build

The site is generated by Zola from `content/spots/*.md`. Each spot
gets one markdown file with TOML frontmatter — the schedule, the
title, station identifiers, links to the official source.

Pool rows on the board carry their schedule in the static HTML as a
`data-schedule` attribute, written by Zola at build time. Pool
status (open / closed hours / closed today) is computed in the
browser by `static/js/status.js` against the visitor's wall-clock
time, so even a deeply cached page reflects the current minute:

```js
// static/js/status.js
const poolRows = root.querySelectorAll('table.board tbody tr[data-type="pool"]');
// ... read row.getAttribute("data-schedule"), compute "OPEN until 7:00 PM"
```

`worker/src/spots.ts` regenerates from `content/spots/*.md` on every
build. That generated file is what the open-water cron iterates over
to know which slugs and station IDs to fetch. There's no runtime
database join between content and the cron — the bridge is a build
step.

Pool detail pages render the day of the week server-side. "Today is
Thursday" is part of the static HTML, with the matching weekday row
highlighted. At midnight Pacific, that HTML goes stale by exactly
one day until the next build. A daily cron fixes it.

{{ diagram(name="day-rollover", caption="One hourly cron. The tick at PT midnight refreshes data and triggers a rebuild.") }}

The cron that refreshes data also handles the rebuild. On the one
hourly tick that lands at 00:00 PT, the handler additionally POSTs
to a Workers Builds deploy hook, which kicks Zola to rebuild and
redeploy:

```ts
// worker/src/schedule.ts
export function isPtMidnight(scheduledTime: number): boolean {
  const ptHour = Number(
    new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      hour: "2-digit",
      hour12: false,
    }).format(new Date(scheduledTime)),
  );
  return ptHour === 0;
}
```

PT midnight maps to one UTC hour per day — `07:00` during PDT,
`08:00` during PST. `Intl` handles the DST shift, so the cron config
stays a single `0 * * * *` entry.

## Live data and caching

The hourly Worker cron has two responsibilities. Always: refresh
data. Sometimes: trigger the daily rebuild.

```ts
// worker/src/index.ts
async scheduled(event, env, ctx) {
  ctx.waitUntil(assembleAndPersist(env.CONDITIONS).catch(...));
  if (isPtMidnight(event.scheduledTime)) {
    ctx.waitUntil(triggerRebuild(env.WORKERS_BUILDS_DEPLOY_HOOK, ...));
  }
},
```

`assembleAndPersist` runs through the five open-water spots in
parallel, fetches upstream data, and writes a single KV value:

```ts
// worker/src/kv.ts
const KEY = "conditions";
```

Four upstream stations feed the records: NOAA `9414290` (bay water
temp + tides), NOAA `9414750` (fallback bay temp), NOAA `9414275`
(Ocean Beach / Baker / China tide predictions), and NDBC buoy
`46237` (ocean water temp).

{{ diagram(name="cache", caption="Cron writes one KV key. Fetch reads it. NOAA and NDBC sit behind the cron, off the request path.") }}

### Tolerating upstream failure

Stations go offline. The bay water temp sensor was dark for most of
a week last winter. Each spot's record carries two stale flags:
`temp_stale` and `tide_stale`, set when the assembler reused the
previous KV value because the upstream fetch came back empty. The
flags are per-field rather than per-record so the UI can mark a
reused tide reading without making a fresh temperature look stale.

{{ diagram(name="fallback", caption="Primary down, fallback down — the assembler reuses the previous KV value and marks the field stale.") }}

The temperature fetch tries the secondary station when the primary
returns nothing or errors:

```ts
// worker/src/noaa.ts
export async function fetchTempWithFallback(primaryId, fallbackId) {
  try {
    const reading = await fetchNoaaTemp(primaryId);
    if (reading) return reading;
  } catch (err) { console.error(...); }
  if (!fallbackId) return null;
  try {
    return await fetchNoaaTemp(fallbackId);
  } catch (err) { console.error(...); return null; }
}
```

If both come back empty, the assembler reuses the previous KV
record's fields and marks the appropriate flag. The freshness
ceiling is twenty-four hours — past that, the fields go to `null`
and the UI shows a dash. Stale data old enough to mislead is worse
than no data.

### Serving the response

The browser fetches `/api/conditions` once after the page loads and
keys into the response by slug:

```js
// static/js/conditions.js
const rows = root.querySelectorAll('table.board tbody tr[data-type="open_water"]');
// ... fill conditions[slug] into the row
```

The Worker's fetch handler writes successful responses to
`caches.default` on miss and serves from there on subsequent
requests in the same colo. With `Cache-Control: public, max-age=900`
and `Vary: Origin`, each allowed origin gets its own 15-minute cache
entry per region:

```ts
// worker/src/index.ts
const cache = caches.default;
const cacheKey = new Request(CONDITIONS_CACHE_KEY_URL, request);

const cached = await cache.match(cacheKey);
if (cached) return cached;

const raw = await readConditionsRaw(env.CONDITIONS);
// ... build response ...
ctx.waitUntil(cache.put(cacheKey, response.clone()));
```

{{ diagram(name="api", caption="Edge cache fronts the Worker fronts KV. Most requests in any given colo never reach KV, let alone NOAA.") }}

Most fetches in any given region never read KV — the edge serves
straight from cache. The browser holds the same response for the
same fifteen minutes, so the typical visitor never reaches the
Worker at all.

## Serving infrastructure and cost

The whole site runs on Cloudflare's free tier. There's exactly one
Worker, exactly one KV namespace, and Workers Builds for the static
build:

{{ diagram(name="workers", caption="Two entry points: fetch and scheduled. Both go through the conditions key in KV.") }}

Costs add up like this, against Cloudflare's published free-tier
limits as of 2026:

| Resource | Free tier | Used |
|---|---|---|
| Workers requests | 100,000 / day | well under (~few thousand visits/day, mostly edge-cached) |
| Worker CPU | 10 ms / request | <2 ms typical (one cache lookup + maybe one KV read) |
| KV reads | 100,000 / day | hundreds — only on cache miss, once per colo per 15 min |
| KV writes | 1,000 / day | 24 (one per hourly cron tick) |
| Workers Builds | 3,000 build-min / month | ~30 (one daily rebuild + push-driven deploys) |
| Static asset bandwidth | unlimited | n/a |

Out-of-pocket cost is the domain registration. Everything else is
zero on this traffic shape, with substantial headroom — Workers
free-tier requests would cover roughly 30× the current traffic
before hitting any limit, and KV reads scale with cache misses, not
with visitors.

The two paid additions worth flagging: Anthropic and Google API
calls during PDF extraction. Those run from a developer machine or
weekly GitHub Action, not the production Worker. With a few
extractions per quarter (PDFs change infrequently) and grounding
running on cached PDF text rather than the LLM, the bill is low —
under $1/month at current cadence on either provider.

## A few tidbits

The set-point temperatures shown under WATER on the pool detail
pages didn't come from a public source. SF Rec & Park doesn't
publish them anywhere I could find. I sent them an email asking if
the official numbers existed; they wrote back with the figures. The
temperatures display on each pool's detail page with attribution in
the page footer.

The "yesterday's data is better than no data" call surfaced in
several places independently. The temperature fallback chain reuses
the previous KV value with a stale flag. The validation gate refuses
sessions-dropped-to-zero rather than silently writing it. The
schedule pipeline's reviewed-snapshot lock projects whatever was
last approved. The pattern wasn't planned; it's what kept happening
when an upstream went weird.

The frontend has no bundler and no framework. Every JS file in
`static/js/` is shipped as-is via `<script type="module">`. The home
page total wire weight, gzipped, is around 50 KB including the map
view (which lazy-loads Leaflet only when the map button is clicked).
This isn't a moral statement about JavaScript ecosystems; it's that
the site has so little client logic that adding a build step would
be more code than the JS it builds.
