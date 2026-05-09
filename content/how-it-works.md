+++
title = "How it works"
description = "The micro-systems behind Swim Francisco — Workers + KV, LLM PDF extraction, caching, day rollover, NOAA fallback."
template = "how-it-works.html"
insert_anchor_links = "left"

[extra]
commit_sha = "7d75629"
github_repo = "https://github.com/cbzehner/swimfrancisco"
+++

The site you're reading from is a static Zola build served by a single
Cloudflare Worker. The Worker also handles `/api/conditions`, fetches NOAA
and NDBC data on an hourly cron, caches the assembled records in KV, and
triggers a daily rebuild at 00:05 Pacific. There's a Python pipeline that
hands SF Rec & Park pool schedule PDFs to an LLM and refuses to write the
result if it looks wrong.

This page walks through six micro-systems behind that, in the order a
request to the homepage exercises them.

{{ diagram(name="overview", caption="Full-system flow: build, request, cron.") }}

## One combined `/api/conditions` endpoint

The board renders fourteen rows. Five are open-water spots that need a
water temperature and a tide; the rest are pools whose schedules ship with
the static build. A naive design fans out one request per spot — fourteen
JSON loads on first paint.

The Worker collapses that. A single `GET /api/conditions` returns every
spot's record, keyed by slug, in one ~6 KB JSON document. The page-load
cost is one request, regardless of how many spots are on the board.

{{ diagram(name="api", caption="One request returns the whole board, not one per spot.") }}

```ts
// worker/src/index.ts
if (path === "/api/conditions") {
  return handleAll(request, env);
}

const spotMatch = path.match(/^\/api\/conditions\/([a-z0-9-]+)$/);
if (spotMatch) {
  return handleSpot(request, env, spotMatch[1]);
}
```

There's also a per-spot endpoint for the detail pages, but the home page
never touches it. KV stores the bulk record under a single `all` key
alongside the per-slug keys, so reading the whole board costs one KV read,
not fourteen.

## Cloudflare Workers + KV

The Worker has two jobs. On HTTP requests it serves the static Zola build
(via Workers Static Assets) and answers `/api/*`. On a cron tick it fetches
fresh data and writes KV. There's no application server in between.

{{ diagram(name="workers", caption="One Worker, two entry points: fetch and scheduled.") }}

KV is layered out as one key per spot plus one bulk key:

```ts
// worker/src/kv.ts
const PREFIX = "conditions:";
const ALL_KEY = "all";

export async function readAllRaw(kv: KVNamespace): Promise<string | null> {
  return kv.get(ALL_KEY);
}

export async function readSpotRaw(kv: KVNamespace, slug: string): Promise<string | null> {
  return kv.get(`${PREFIX}${slug}`);
}
```

The home page reads `all`. Spot pages read `conditions:<slug>`. The cron
writes both — fifteen keys total — once an hour.

```ts
// worker/src/index.ts
async fetch(request, env) {
  if (request.method !== "GET") {
    return new Response("method not allowed", { status: 405, ... });
  }
  // route to handleAll / handleSpot
},

async scheduled(event, env, ctx) {
  if (classifyTick(event.scheduledTime) === "rebuild") {
    ctx.waitUntil(triggerRebuild(env.WORKERS_BUILDS_DEPLOY_HOOK, ...));
    return;
  }
  ctx.waitUntil(assembleAndPersist(env.CONDITIONS).catch(...));
},
```

The map view lazy-loads Leaflet, so the home page ships ~50 KB of HTML +
CSS + JS over the wire. No bundler. No framework. Vanilla `<script
type="module">` and a `main.css`.

## LLM PDF extraction (kept honest)

The pool schedules don't come from an API. They come from PDFs hosted on
sfrecpark.org — calendar grids with program labels and time ranges
distributed across cells, formatted differently per pool. There's no
official feed.

The original plan was a regex parser. It died fast. Calendar PDFs serialize
through `pypdf` with the program label and time range often on different
lines, with cells from other days interleaved between them. Any regex
strict enough to be correct missed half the rows; any regex loose enough
to catch them all matched garbage.

The current pipeline hands each PDF to an LLM (Anthropic or Gemini, with
a bakeoff mode) and asks for structured JSON. That alone would be too
fragile for the homepage, so there are four safety nets between the model
and `content/spots/*.md`.

{{ diagram(name="pdf-extraction", caption="PDF → LLM → grounding → validation → reviewed lock → merge.") }}

**1. SHA-keyed cache.** Every fetched PDF is keyed by its SHA-256. A
matching SHA reuses the existing review directory; a mismatch triggers a
fresh extraction. This avoids re-running the LLM on byte-identical inputs
and makes "did the PDF change?" a `==` on a hash.

**2. Grounding.** Every extracted session must come with an evidence
string. The grounding step normalizes the PDF text and checks that the
evidence's significant tokens appear *in order* within a ~250-character
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
don't appear contiguous. The window-and-order check tolerates the
layout while still rejecting hallucinations.

**3. Validation gate.** Even with grounded evidence, the writer refuses
the payload if it looks catastrophically wrong:

```python
# schedule-tools/src/schedules/validate.py
if prior_sessions_count and len(sessions) == 0:
    violations.append(Violation(
        code="sessions_dropped_to_zero",
        message="sessions_count dropped to 0 from a previously non-zero state",
    ))
    catastrophic = True
```

If a pool had thirty drop-in sessions yesterday and the LLM extracts zero
today, the merge step is blocked. The PDF probably changed in a way the
prompt doesn't handle yet, and silently writing an empty schedule would
be worse than yesterday's slightly stale data.

**4. Reviewed-snapshot lock.** Once an operator manually reviews an
extraction, a `reviewed.json` keyed to the PDF's SHA is written. The
fast-path skips the LLM entirely until the PDF changes:

```python
# schedule-tools/src/schedules/pipeline.py
if not force and not compare_with and reviewed_file.exists():
    return _build_unchanged(entry, fetch_result, reviewed_file)
```

> *Aside.* The pools whose set-point temperatures show under WATER on
> their detail pages came from an email to SF Rec & Park asking for
> official targets. They responded. The temperatures display with the
> source attributed in the footer.

## Caching and serving

The hourly cron is what keeps the temps and tides on the board fresh.
Each tick fetches the upstream sources, assembles a record per spot,
and writes KV. The HTTP handler never calls NOAA or NDBC — it only
reads what the last cron put in KV.

{{ diagram(name="cache", caption="Cron writes KV; fetch reads KV. NOAA and NDBC are never on the request path.") }}

The cache layering on the JSON response is deliberate:

```ts
// worker/src/index.ts
// Data refreshes hourly via cron; bound clients to 5min and edge to 15min.
const JSON_CACHE_CONTROL = "public, max-age=300, s-maxage=900";
```

Five minutes on the client and fifteen at the Cloudflare edge means most
visitors never reach the Worker at all. The hourly cron is the upstream
refresh rate; the cache TTLs are tuned so the edge stays fresh enough to
match.

The assembly step also tolerates upstream failure. Each spot's record
carries a per-field stale flag — `temp_stale` and `tide_stale` — set
when the assembler had to reuse the previous KV value because the
upstream fetch returned nothing:

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

The flag was a single `stale: bool` originally. When the tide station
went offline but the temperature reading was fine, the whole record got
marked stale and the UI flagged the temperature as old too. Splitting
into per-field flags lets the UI show that one reading is stale without
casting doubt on the rest.

## Day rollover at 00:05 PT

The home page renders the day of the week server-side. "Today is
Thursday" is part of the static HTML. So at midnight Pacific, the page
goes stale by exactly one day until the next build.

The fix is a daily rebuild. Two daily crons in `wrangler.toml` cover
PST (`5 8 * * * UTC`) and PDT (`5 7 * * * UTC`), so one fires at 00:05
Pacific year-round. The hourly cron at minute 0 keeps doing its
data-refresh job alongside it.

{{ diagram(name="day-rollover", caption="PT vs. UTC: two daily crons cover DST; the hourly cron is unaffected.") }}

The Worker dispatches by classifying the tick. Pacific hour 0 + UTC
minute 5 means rebuild; everything else means refresh:

```ts
// worker/src/schedule.ts
export function classifyTick(scheduledTime: number): TickKind {
  const at = new Date(scheduledTime);
  const ptHour = Number(
    new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      hour: "2-digit",
      hour12: false,
    }).format(at),
  );
  const minute = at.getUTCMinutes();
  return ptHour === 0 && minute === 5 ? "rebuild" : "refresh";
}
```

The minute-5 offset is the only reason the hourly cron and the daily
rebuild can coexist. Minute 0 is owned by data refresh; the rebuild
takes minute 5.

## NOAA / NDBC fallback

Three upstream sources feed the open-water spots: NOAA station 9414290
(bay temperature + tides), 9414750 (a fallback temperature station for
the bay), and NDBC buoy 46237 (ocean temperature). Stations go offline.
The bay temperature sensor was dark for most of a week last winter.

{{ diagram(name="fallback", caption="When a station is silent, the assembler reuses the last good KV value and marks the field stale.") }}

The temperature fetch falls back to a secondary station when the primary
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

If both primary and fallback come back empty, the assembler reads the
previous KV record and reuses its temperature fields, marking
`temp_stale: true`. The same is true for tides: `tide_stale: true` when
the prediction was reused from the last good value.

The freshness ceiling is twenty-four hours. If the previous record is
older than that, the fields go to `null` and the UI shows a dash. Stale
data that's stale enough to mislead is worse than no data.

---

The site is open source. Code excerpts above are pinned to commit
[`{{ page.extra.commit_sha }}`]({{ page.extra.github_repo }}/tree/{{ page.extra.commit_sha }}).
Browse the current source at [{{ page.extra.github_repo }}]({{ page.extra.github_repo }}).
