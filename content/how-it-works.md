+++
title = "How it works"
description = "The architecture behind Swim Francisco — three paths through one Worker plus an offline LLM pipeline."
template = "how-it-works.html"
insert_anchor_links = "left"

[extra]
commit_sha = "3be5725"
github_repo = "https://github.com/cbzehner/swimfrancisco"
+++

Swim Francisco is a live status board for fourteen places to swim in
San Francisco: nine city pools and five open-water spots. The system
has three paths through it. The page walks each in turn.

1. **Request path.** The browser loads static HTML, computes pool
   status from schedules embedded in the page, and fetches
   `/api/conditions` for live water temperatures and tides on the
   five open-water spots.
2. **Scheduled path.** An hourly Cloudflare Worker cron fetches NOAA
   and NDBC, assembles five open-water records, and writes a single
   KV value. The tick that lands at 00:00 PT also pings the Workers
   Builds deploy hook to roll date-sensitive HTML forward.
3. **Content path.** Pool schedule PDFs are fed to an LLM, surface as
   review candidates with grounding and validation signals, get
   approved by a human, and land in `content/spots/*.md` — which
   Zola compiles into the static site on each deploy.

{{ diagram(name="overview", caption="Build, request, cron — three paths through one Worker.") }}

## The request path

The board has fourteen rows. Pool rows and open-water rows hydrate
from different places.

**Pool rows** carry their schedule in the static HTML as a
`data-schedule` attribute, written by Zola at build time from the
pool's `content/spots/<slug>.md` frontmatter. Status (open / closed
hours / closed today) is computed in the browser by `static/js/status.js`
against the visitor's wall-clock time:

```js
// static/js/status.js
const poolRows = root.querySelectorAll('table.board tbody tr[data-type="pool"]');
// ... read row.getAttribute("data-schedule"), compute "OPEN until 7:00 PM" etc.
```

**Open-water rows** also load from static HTML, but their water
temperature and next tide come from a single `GET /api/conditions`
fetch after page load:

```ts
// worker/src/index.ts
if (path === "/api/conditions") {
  return handleConditions(request, env);
}
```

The endpoint returns one slug-keyed JSON document containing the five
open-water records:

{{ diagram(name="api", caption="One fetch hydrates the open-water rows. Pool rows hydrate from static schedule data.") }}

`static/js/conditions.js` keys into the response by slug and injects
temperatures, tides, and stale flags into matching rows on the board
and any open-water detail pages:

```js
// static/js/conditions.js
const rows = root.querySelectorAll('table.board tbody tr[data-type="open_water"]');
// ... fill conditions[slug] into the row
```

The Worker writes successful responses to `caches.default` on miss
and serves from there on subsequent requests in the same colo. With
`Cache-Control: public, max-age=900` and `Vary: Origin`, each allowed
origin gets its own 15-minute cache entry per region:

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

Most fetches in any given region never read KV — the edge serves
straight from cache. The browser holds the same response for the
same fifteen minutes, so the typical visitor never reaches the
Worker at all.

## The scheduled path

The Worker has two entry points. `fetch` handles HTTP for `/api/*`
and falls through to Workers Static Assets for everything else.
`scheduled` runs once an hour and does two things on the same tick:
always refresh data, and rebuild the static site on the tick that
lands at PT midnight.

{{ diagram(name="workers", caption="Two entry points: fetch and scheduled. Both go through the conditions key in KV.") }}

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
parallel, fetches upstream data, and writes a single key:

```ts
// worker/src/kv.ts
const KEY = "conditions";
```

The set of spots and their station bindings are auto-generated from
`content/spots/*.md` into `worker/src/spots.ts` at build time, which
is how the content path and the scheduled path stay in sync without a
runtime database join.

Four upstream stations feed the open-water records:
NOAA `9414290` (bay water temp + tides), NOAA `9414750` (fallback
bay temp), NOAA `9414275` (Ocean Beach / Baker / China tide
predictions), and NDBC buoy `46237` (ocean water temp).

{{ diagram(name="cache", caption="Cron writes one KV key. fetch reads it. NOAA and NDBC sit behind the cron, off the request path.") }}

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

### Day rollover at 00:00 PT

Pool detail pages render the day of the week server-side. "Today
is Thursday" is part of the static HTML, with the matching weekday
row highlighted. At midnight Pacific, that HTML goes stale by
exactly one day until the next build.

The fix runs off the same hourly cron. On the one tick that lands
at 00:00 PT, the handler also POSTs to a Workers Builds deploy
hook, which kicks Zola to rebuild and redeploy.

{{ diagram(name="day-rollover", caption="One hourly cron. The tick at PT midnight refreshes data and triggers a rebuild.") }}

The check is a small helper that asks `Intl` for the PT hour, which
handles the PDT/PST shift transparently:

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
`08:00` during PST. The cron config never has to know which; the
handler asks the question fresh on every tick.

## The content path

SF Rec & Park doesn't publish pool schedules as data. They publish
PDFs: calendar grids with program labels and time ranges in cells,
formatted differently per pool, on sfrecpark.org.

A regex parser was the first attempt. It was too brittle for the
layout: `pypdf` extracts the program label and the time range on
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

**2. Grounding (advisory).** Every extracted session must come
with an evidence string. The grounding step normalizes the PDF text
and checks that the evidence's significant tokens appear *in order*
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
automated step that actually refuses an extraction. It fires on
payloads that look catastrophically wrong:

```python
# schedule-tools/src/schedules/validate.py
if prior_sessions_count and len(sessions) == 0:
    violations.append(Violation(
        code="sessions_dropped_to_zero",
        message="sessions_count dropped to 0 from a previously non-zero state",
    ))
    catastrophic = True
```

If a pool had thirty drop-in sessions yesterday and the LLM
extracts zero today, the run exits non-zero. The PDF probably
changed in a way the prompt doesn't handle yet; better to surface
that as a hard failure than as an empty review queue entry that
might get rubber-stamped.

**4. Human review.** Anything that survives catastrophic
validation lands as a review candidate — provider artifacts under
`data/<slug>/<date>-<sha12>/` plus a markdown report in `tmp/`.
The operator runs `schedules review`, which opens the source PDF
and a draft `reviewed.json` in their editor side by side. On save,
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

`worker/src/spots.ts` regenerates from `content/spots/*.md` on every
build, so a newly-approved schedule reaches both the static HTML and
the cron's spot list on the next deploy.

> *Aside.* The set-point temperatures shown under WATER on the pool
> detail pages came from an email I sent to SF Rec & Park asking for
> the official numbers. They wrote back. The temperatures display
> with attribution in the page footer.
