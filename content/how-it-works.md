+++
title = "How it works"
description = "I built a status board for the fourteen places to swim in San Francisco. PDFs through an LLM, NOAA hourly, all on one Cloudflare Worker for the cost of a domain name."
template = "how-it-works.html"
insert_anchor_links = "left"

[extra]
commit_sha = "d6f35c1"
+++

Last winter I was trying to answer one boring question before
leaving the house: can I swim right now?

The answer was split across a city PDF, the pool's detail page on
sfrecpark.org, NOAA water temperature, NOAA tide predictions, and —
for the ocean spots — a different NOAA station entirely. Every
source was public. None of it was assembled.

Swim Francisco is the page I wanted. Fourteen swim spots in San
Francisco — nine pools and five open-water spots — on one board,
with pool status, bay and ocean temperature, and the next tide.
There's no app, no account, no ads, no tracking. The audience is me
and people like me, checking before heading out.

The system underneath is small: Zola for the static build, one
Cloudflare Worker, one KV key, hourly NOAA/NDBC fetches, and a
human-reviewed LLM pipeline for the city's pool PDFs. The runtime
path is just edge cache, Worker, KV.

This page is how it's wired together, and why some of it is wired
the way it is.

## What's running here

Three pipelines feed one static site.

Pool schedules come from PDFs on sfrecpark.org. An LLM extracts
them. I review every result against the source by hand. The
approved data lands as markdown frontmatter that Zola compiles into
HTML.

Open-water conditions come from NOAA and NDBC. A Cloudflare Worker
cron fetches them every hour, tolerates upstream failures with last-
good fallbacks, and writes one slug-keyed JSON record to KV.

The Worker is also the HTTP server. The browser loads static HTML,
computes pool status from schedule data embedded in the page, and
fetches `/api/conditions` once to hydrate live water temperatures
and tides on the open-water rows. Most of those fetches never hit
the origin: Cloudflare's edge caches the response.

{{ diagram(name="overview", caption="Build, request, cron — three paths through one Worker.") }}

The runtime never calls an LLM. PDF extraction is offline tooling
that runs from my laptop or weekly from a GitHub Action. By the
time anyone hits the site, the schedules in `content/spots/*.md`
are static text I approved by hand.

## Reading the PDFs

I tried regex first.

`pypdf` extracts text from a PDF page in reading order — but on a
calendar grid, that order interleaves cells from different days.
The program label `LAP SWIM` would land on one line, the time range
`6:00 AM – 7:30 AM` on another, with three unrelated cells between
them. A regex strict enough to be correct missed half the rows. A
regex loose enough to catch them all matched garbage. I shipped
that, watched it produce wrong schedules, and threw it out within a
week.

The current pipeline hands each PDF to Anthropic or Gemini and asks
for structured JSON. That alone isn't trustworthy enough for a
homepage, so four guardrails sit between the model output and
content:

| Guardrail | Blocks? | Catches |
|---|:---:|---|
| SHA cache | yes | unchanged PDFs (skip the LLM) |
| Grounding | no | rows the model paraphrased rather than read |
| Validation | yes | catastrophic drops (sessions → 0) |
| Human review | yes | plausible-but-wrong extractions |

{{ diagram(name="pdf-extraction", caption="Reviewed-lock SHA match fast-paths to content. Otherwise LLM → grounding → validation; catastrophic refusal exits non-zero, everything else awaits human review before content/spots is touched.") }}

**SHA cache.** Each fetched PDF gets a SHA-256. A matching SHA
reuses the existing review directory; a mismatch triggers a fresh
extraction. "Did the PDF change?" becomes hash equality.

**Grounding (advisory).** Every extracted session must carry an
evidence string. A normalize-and-window check verifies the
evidence's significant tokens appear *in order* within a 250-character
window of the PDF text. A literal substring check fails on calendar
PDFs because the tokens don't print contiguous; the window-and-order
tolerance accepts the messy layout but still rejects answers the
model paraphrased from outside the source.

`schedule-tools/src/schedules/grounding.py`

```python
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

Coverage shows up in the review report as a percentage so I know
which sessions to scrutinize. It doesn't block the extraction.

**Validation gate.** If a pool had thirty drop-in sessions yesterday
and the LLM extracts zero today, the run exits non-zero. The PDF
probably changed in a way the prompt doesn't handle yet; better to
surface that as a hard failure than as an empty review queue entry I
might rubber-stamp at midnight.

`schedule-tools/src/schedules/validate.py`

```python
if prior_sessions_count and len(sessions) == 0:
    violations.append(Violation(
        code="sessions_dropped_to_zero",
        message="sessions_count dropped to 0 from a previously non-zero state",
    ))
    catastrophic = True
```

**I review the rest by hand.** Whatever survives validation lands
as a review candidate — provider artifacts under
`data/<slug>/<date>-<sha12>/` and a markdown report. Running
`schedules review` opens the source PDF and a draft `reviewed.json`
in my editor side by side. On save, `finalize_draft` rejects the
draft if it's byte-identical to the provider's payload (no review
actually happened) and otherwise projects the approved payload into
`content/spots/<slug>.md` and writes the `reviewed.json` keyed to
the PDF's SHA. Future runs short-circuit until the PDF changes.

## Static build

Zola compiles `content/spots/*.md` into HTML. Each spot is one
markdown file with TOML frontmatter — schedule, title, station IDs,
links to the official source.

Pool rows on the board carry their schedule directly in the static
HTML as a `data-schedule` attribute. The browser reads it back and
computes status (open / closed hours / closed today) against the
visitor's wall-clock time, so even a deeply cached page reflects the
current minute.

`static/js/status.js`

```js
const poolRows = root.querySelectorAll('table.board tbody tr[data-type="pool"]');
// ... read row.getAttribute("data-schedule"), compute "OPEN until 7:00 PM"
```

The frontend has no bundler and no framework. Every JS file in
`static/js/` ships as-is via `<script type="module">`. The home page
total wire weight, gzipped, is around 50 KB including the map view
— Leaflet only loads when someone clicks the map button. This isn't
a moral statement about JavaScript ecosystems. The site has so
little client logic that adding a build step would be more code
than the JS it builds.

The build also generates `worker/src/spots.ts` from the same
`content/spots/*.md` files. That generated TypeScript is what the
open-water cron iterates over to know which slugs and stations to
fetch. There's no runtime database join between content and the
cron — the bridge is a build step.

The first version of that build step lived in `wrangler.toml` as a
`[build]` hook that ran `node ../scripts/generate-worker-spots.mjs`
on every deploy. That worked locally and broke production. Cloudflare
Workers Builds runs the hook from `/opt/buildhome/repo`, not from
the directory holding `wrangler.toml`, so `../scripts/...` resolved
outside the cloned repo. Two pushes failed silently; production sat
on a stale Worker for a day before I noticed. The fix was less
clever: commit the generated `spots.ts`, regenerate it before
typecheck so it stays current locally, and let a parity test fail
in CI if `content/spots/*.md` and `worker/src/spots.ts` ever drift.

Pool detail pages render the day of the week server-side. "Today is
Thursday" lives in the static HTML, with the matching weekday row
highlighted. At midnight Pacific the HTML goes stale by exactly one
day until the next deploy. I solved that with a daily rebuild that
piggybacks on the existing hourly cron — when the cron tick lands
at 00:00 PT, the handler also POSTs to a Workers Builds deploy hook.

`worker/src/schedule.ts`

```ts
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

## Live data and caching

The Worker's `scheduled` handler runs once an hour. Every tick:
fetch upstream, write KV. The PT-midnight tick also fires the
rebuild.

`worker/src/index.ts`

```ts
async scheduled(event, env, ctx) {
  ctx.waitUntil(assembleAndPersist(env.CONDITIONS).catch(...));
  if (isPtMidnight(event.scheduledTime)) {
    ctx.waitUntil(triggerRebuild(env.WORKERS_BUILDS_DEPLOY_HOOK, ...));
  }
},
```

`assembleAndPersist` fetches the five open-water spots in parallel
and writes one KV value at the key `conditions`. Four upstream
stations feed those records: NOAA `9414290` for bay water
temperature and tides, NOAA `9414750` as a fallback bay temperature
station, NOAA `9414275` for tide predictions at Ocean Beach / Baker
/ China, and NDBC buoy `46237` for ocean water temperature.

The KV layout used to be different. The original design had one key
per spot plus a bulk key called `all`, fronted by `/api/conditions`
for the bulk read and `/api/conditions/:slug` for per-spot reads.
Detail pages never used the per-spot route — they keyed into the
bulk response by slug. So the cron did 14 reads + 15 writes every
hour to feed an endpoint nothing called. Collapsing to one
`conditions` key dropped that to 1 read + 1 write per tick and made
the cost table boring.

### Yesterday's data beats no data

Stations go offline. The bay water temp sensor was dark for most of
a week last winter. Each spot's record carries two stale flags —
`temp_stale` and `tide_stale` — set when the assembler reused the
previous KV value because the upstream fetch came back empty.

> *Stale data old enough to mislead is worse than no data.*

The flags are per-field on purpose. The first version had a single
`stale: bool`, and the first time a tide station went down with a
healthy temperature reading, the record marked the *temperature* as
stale because the *whole record* was reused. Splitting into
`temp_stale` and `tide_stale` lets the UI flag only what actually
came from cold storage.

The same principle ended up everywhere: the temperature fallback
chain reuses the previous KV value, the validation gate refuses
sessions-dropped-to-zero rather than silently writing it, and the
reviewed-snapshot lock keeps `content/spots` stable until I approve
a new extraction. I didn't plan the pattern. It kept being the
answer when an upstream went weird.

{{ diagram(name="fallback", caption="Primary down, fallback down — the assembler reuses the previous KV value and marks the field stale.") }}

The temperature fetch tries the secondary station when the primary
returns nothing or errors. If both come back empty, the assembler
reuses the previous KV record's temperature with `temp_stale: true`.
Tides work the same way. The freshness ceiling is twenty-four hours
— past that, the fields go to `null` and the UI shows a dash.

`worker/src/noaa.ts`

```ts
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

### The edge cache (and one place I lied)

The fetch handler checks `caches.default` first, serves any hit, and
on miss reads KV, builds the response, and writes to the cache
asynchronously via `ctx.waitUntil`. With `Cache-Control: public,
max-age=900` and `Vary: Origin`, each allowed origin gets its own
15-minute cache entry per Cloudflare colo.

```ts
const cache = caches.default;
const cacheKey = new Request(CONDITIONS_CACHE_KEY_URL, request);

const cached = await cache.match(cacheKey);
if (cached) return cached;

const raw = await readConditionsRaw(env.CONDITIONS);
// ... build response ...
ctx.waitUntil(cache.put(cacheKey, response.clone()));
```

That's the current design. The earlier version of this writeup
described it the same way — and was wrong. The Worker set the
Cache-Control header but never wrote to `caches.default`. Browsers
cached for 15 minutes; every cache miss read KV. I had to either
soften the prose to match the code or fix the code to match the
prose. I fixed the code.

There's a second gotcha I haven't fixed yet. Production currently
serves `Cache-Control: public, max-age=14400` (four hours), not the
fifteen minutes the Worker sets. Cloudflare's zone-level Browser
Cache TTL setting is rewriting the response header on egress. With
hourly data, a four-hour browser cache means a visitor refreshing
at the wrong moment can see open-water data up to about five hours
old. Pool status is fine — it's computed client-side from
server-rendered schedule HTML, so it's always current to the minute.
But the open-water numbers can lag. Outstanding to-do: flip the zone
setting to "Respect Existing Headers" and let the Worker's 15-minute
TTL win. If you're deploying a Worker with a Cache-Control header
and your data looks oddly stale, your zone might be quietly
overriding you.

## What it costs

Everything runs on Cloudflare's free tier. One Worker, one KV
namespace, Workers Builds, and Workers Static Assets:

| Resource | Free tier (2026) | Used |
|---|---|---|
| Workers requests | 100k / day | well under (most served from edge cache) |
| Worker CPU | 10 ms / request | typically 1–2 ms |
| KV reads | 100k / day | hundreds — only on cache miss |
| KV writes | 1k / day | 24 (one per hourly cron tick) |
| Workers Builds | within free-tier monthly minutes | ~30 build-min / month |
| Static asset bandwidth | unlimited | n/a |

Out-of-pocket cost is the domain registration. Anthropic and Google
API calls during PDF extraction add another line item, but those
run from my laptop or weekly from CI, not on the production Worker.
Pool PDFs change rarely — a quarter or so of the year — so the bill
is well under a dollar a month on either provider.

I haven't bothered measuring the precise hit rate or daily request
count. The point of the table isn't a cost-tuning exercise; it's
that nothing on this list is even close to a boundary, with
substantial headroom to grow.

## Notes

The set-point temperatures shown under WATER on the pool detail
pages weren't published anywhere I could find. I emailed SF Rec &
Park asking whether the official numbers existed. They wrote back
with the figures, which is how every pool's detail page now shows
the set-point with attribution in the footer.

One of the nine pools — Sava — is currently closed without a
published schedule. The board still lists it; the pipeline marks
it `source_status = "closed_without_current_schedule"` and the page
shows the closure. Making the registry honest about that was easier
than making the page pretend.

---

I didn't build this to learn a new framework. I built it to go
swimming without fighting a PDF. Keeping the client dumb, treating
the LLM as an untrusted data parser behind a human review gate, and
letting Cloudflare's edge do the serving means the site costs the
price of a domain and asks for almost no maintenance. That's the
whole architecture.
