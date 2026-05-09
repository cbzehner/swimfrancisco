+++
title = "How it works"
description = "The micro-systems behind Swim Francisco — Workers + KV, LLM PDF extraction, caching, day rollover, NOAA fallback."
template = "how-it-works.html"
insert_anchor_links = "left"

[extra]
commit_sha = "7d75629"
github_repo = "https://github.com/cbzehner/swimfrancisco"
+++

Swim Francisco is a live status board for fourteen places to swim in San
Francisco: nine city pools and five open-water spots. One Cloudflare
Worker serves the whole site — static pages, API, hourly data refresh,
daily rebuild. A small Python pipeline hands pool schedule PDFs to an
LLM and refuses to write the result if it looks wrong.

This page walks through six pieces of that, in the order a request to
the home page exercises them.

{{ diagram(name="overview", caption="Build, request, cron — three paths through one Worker.") }}

## One combined `/api/conditions` endpoint

The home page renders fourteen spots and makes one HTTP request to do
it. A naïve design would make fourteen, one per row.

The Worker collapses the fan-out. `GET /api/conditions` returns every
spot's record, keyed by slug, in one ~6 KB JSON document:

```ts
// worker/src/index.ts
if (path === "/api/conditions") {
  return handleConditions(request, env);
}
```

{{ diagram(name="api", caption="One request returns the whole board, not one per spot.") }}

Detail pages reuse the same response and key into it by slug, so every
page on the site is hydrated by a single edge-cached fetch. KV holds
the slug-keyed record under one key, so reading the whole board costs
one KV read, not fourteen.

## Cloudflare Workers + KV

The Worker has two jobs. On HTTP requests it serves the static Zola
build (via Workers Static Assets) and answers `/api/*`. On a cron tick
it fetches fresh data and writes KV. Nothing else lives in between.

{{ diagram(name="workers", caption="Two entry points: fetch and scheduled. Both go through KV.") }}

KV holds the single conditions record:

```ts
// worker/src/kv.ts
const KEY = "conditions";

export async function readConditionsRaw(kv: KVNamespace): Promise<string | null> {
  return kv.get(KEY);
}

export async function writeConditions(kv: KVNamespace, value: Conditions): Promise<void> {
  await kv.put(KEY, JSON.stringify(value));
}
```

Every page reads `conditions`. The cron writes it once an hour after
assembling all fourteen spot records.

```ts
// worker/src/index.ts
async fetch(request, env) {
  if (request.method !== "GET") {
    return new Response("method not allowed", { status: 405, ... });
  }
  // route to handleConditions
},

async scheduled(event, env, ctx) {
  ctx.waitUntil(assembleAndPersist(env.CONDITIONS).catch(...));
  if (isPtMidnight(event.scheduledTime)) {
    ctx.waitUntil(triggerRebuild(env.WORKERS_BUILDS_DEPLOY_HOOK, ...));
  }
},
```

The map view lazy-loads Leaflet, so the home page ships about 50 KB of
HTML, CSS, and JS over the wire. No bundler. No framework. Vanilla
`<script type="module">` and a single `main.css`.

## LLM PDF extraction (kept honest)

SF Rec & Park doesn't publish pool schedules as data. They publish
PDFs: calendar grids with program labels and time ranges in cells,
formatted differently per pool, on sfrecpark.org.

The first attempt was a regex parser. It died fast. Calendar PDFs come
out of `pypdf` with the program label and time range often on
different lines, with cells from other days interleaved between them.
A regex strict enough to be correct missed half the rows; a regex loose
enough to catch them all matched garbage.

The current pipeline hands each PDF to an LLM (Anthropic or Gemini,
with a bakeoff mode) and asks for structured JSON. That alone would be
too fragile for a homepage, so four safety nets sit between the model
and `content/spots/*.md`.

{{ diagram(name="pdf-extraction", caption="PDF → SHA cache → LLM → grounding → validation → reviewed lock → merge.") }}

**1. SHA-keyed cache.** Each fetched PDF gets a SHA-256. A matching
SHA reuses the existing review directory; a mismatch triggers a fresh
extraction. "Did the PDF change?" becomes a hash equality.

**2. Grounding.** Every extracted session must come with an evidence
string. The grounding step normalizes the PDF text and checks that the
evidence's significant tokens appear *in order* within a 250-character
window:

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
layout but still rejects answers the model paraphrased.

**3. Validation gate.** Even with grounded evidence, the writer
refuses payloads that look catastrophically wrong:

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
zero today, the merge step blocks the write. The PDF probably changed
in a way the prompt doesn't handle yet. Yesterday's slightly-stale
data beats silently writing an empty schedule.

**4. Reviewed-snapshot lock.** Once an operator reviews an extraction
by hand, a `reviewed.json` keyed to the PDF's SHA is written next to
the source. Future runs short-circuit until the PDF changes:

```python
# schedule-tools/src/schedules/pipeline.py
if not force and not compare_with and reviewed_file.exists():
    return _build_unchanged(entry, fetch_result, reviewed_file)
```

> *Aside.* The set-point temperatures shown under WATER on the pool
> detail pages came from an email I sent to SF Rec & Park asking for
> the official numbers. They wrote back. The temperatures display
> with attribution in the page footer.

## Caching and serving

The hourly cron keeps temps and tides fresh. Each tick fetches the
upstream sources, assembles a record per spot, and writes KV. The HTTP
handler never calls NOAA or NDBC. It only reads what the last cron put
in KV.

{{ diagram(name="cache", caption="Cron writes KV; fetch reads KV. NOAA and NDBC sit behind the cron, off the request path.") }}

The cache headers on the JSON response are tuned to the cron rate:

```ts
// worker/src/index.ts
// Data refreshes hourly via cron; bound clients to 5min and edge to 15min.
const JSON_CACHE_CONTROL = "public, max-age=300, s-maxage=900";
```

Five minutes on the client, fifteen at the Cloudflare edge. Most
visitors never reach the Worker at all — the edge serves the response
straight from cache.

The assembly step also tolerates upstream failure. Each spot's record
carries two stale flags, `temp_stale` and `tide_stale`, set when the
assembler reused the previous KV value because the upstream fetch came
back empty:

```ts
// worker/src/assemble.ts
function coalesceTemp(fresh, previous, previousIsFresh) {
  if (fresh !== null) return { fields: fresh, stale: false };
  if (previousIsFresh) {
    const fallback = tempFromPrevious(previous);
    if (fallback) return { fields: fallback, stale: true };
  }
  return { fields: null, stale: false };
}
```

The flag was a single `stale: bool` originally. When a tide station
went down but the temperature reading was fine, the whole record got
marked stale and the UI flagged the temp as old too. Splitting into
per-field flags lets the UI mark one reading stale without casting
doubt on the rest.

## Day rollover at 00:00 PT

The home page renders the day of the week server-side. "Today is
Thursday" is part of the static HTML. So at midnight Pacific, the page
goes stale by exactly one day until the next build.

The fix runs off the same hourly cron that refreshes data. Twenty-four
times a day the Worker fetches NOAA and NDBC; on the one tick that
lands at 00:00 PT, it also pings the Workers Builds deploy hook.

{{ diagram(name="day-rollover", caption="One hourly cron. The tick at PT midnight refreshes data and triggers a rebuild.") }}

The handler check is a one-liner that asks `Intl` for the PT hour,
which handles the PDT/PST shift transparently:

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

## NOAA / NDBC fallback

Stations go offline. The bay temperature sensor was dark for most of a
week last winter. The page can't just show a dash and shrug — most
readers want a number, even one a few hours old.

Three upstream sources feed the open-water spots: NOAA station 9414290
(bay temperature and tides), 9414750 (a fallback temperature station
for the bay), and NDBC buoy 46237 (ocean temperature).

{{ diagram(name="fallback", caption="Primary down, fallback down — the assembler reuses the previous KV value and marks the field stale.") }}

The temperature fetch tries the secondary station when the primary
returns nothing or errors:

```ts
// worker/src/noaa.ts
export async function fetchTempWithFallback(
  primaryId: string,
  fallbackId: string | undefined,
): Promise<NoaaTempReading | null> {
  try {
    const reading = await fetchNoaaTemp(primaryId);
    if (reading) return reading;
  } catch (err) {
    console.error(`NOAA temp primary ${primaryId} failed:`, err);
  }
  if (!fallbackId) return null;
  try {
    return await fetchNoaaTemp(fallbackId);
  } catch (err) {
    console.error(`NOAA temp fallback ${fallbackId} failed:`, err);
    return null;
  }
}
```

If both come back empty, the assembler reads the previous KV record
and reuses its temperature fields, marking `temp_stale: true`. Tides
work the same way: `tide_stale: true` when the prediction was reused
from the last good value.

The freshness ceiling is twenty-four hours. Past that, the fields go
to `null` and the UI shows a dash. Stale data old enough to mislead is
worse than no data.

---

The site is open source. Code excerpts above are pinned to commit
[`{{ page.extra.commit_sha }}`]({{ page.extra.github_repo }}/tree/{{ page.extra.commit_sha }}).
Browse the current source at [{{ page.extra.github_repo }}]({{ page.extra.github_repo }}).
