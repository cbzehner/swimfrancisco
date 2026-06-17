# Agent Data Mode - Design Decision

**Date:** 2026-06-16
**Status:** Partially implemented - static v1

## Context

Swim Francisco already exposes two useful surfaces for people and
crawlers:

- static Zola pages built from `content/spots/*.md`
- `GET /api/conditions`, served by the Worker from KV and refreshed
  hourly from NOAA / NDBC

The human board answers "where can I swim right now?" by combining
static spot data, schedule frontmatter, client-side status logic, and
live condition JSON. That works for people, but it asks agents to infer
too much from rendered HTML or frontend JavaScript.

The site also has `static/llms.txt`, which is useful discovery, but
`llms.txt` should not become the data carrier. It should point agents to
stable resources that expose the same canonical facts as the human site
without requiring UI scraping.

Cloudflare's Markdown for Agents is a useful reference point:
content negotiation with `Accept: text/markdown`, token-count headers,
frontmatter, JSON-LD preservation, and content-signal headers. For this
project, direct structured resources are a better primary interface
than converting the rendered HTML back into Markdown, because the source
data is already structured.

## Decision

Add an **Agent Data Mode**: a small HTTP contract for LLMs and agents
that serves the same spot, schedule, access, condition, source, and
freshness data as the human site.

This is not a second visual mode and not an MCP server. It is a set of
static build artifacts plus a dynamic Worker snapshot.

The first implementation should be static-first. The dynamic snapshot is
approved only after status computation has one shared implementation
that both the browser and Worker can use.

Static v1 is implemented by `scripts/generate-agent-data.mjs`, which
writes ignored build artifacts under `public/agent/` after `zola build`.
The dynamic `/agent/snapshot.json` endpoint remains deferred.

## Goals

- Let agents answer "where can I swim right now?" without running
  JavaScript or scraping visual HTML.
- Keep static spot facts and live condition facts on their existing
  update paths.
- Include enough source and freshness metadata for agents to cite
  answers honestly.
- Keep `llms.txt` as discovery, not as the canonical data payload.
- Prefer boring JSON first; add Markdown representations where they
  improve readability or compatibility.

## Non-goals

- No MCP server in v1.
- No separate agent-only database.
- No agent-specific facts that can drift from `content/spots/*.md` or
  `/api/conditions`.
- No client-side rendering requirement for agent resources.
- No natural-language answer endpoint. Agents compose answers from the
  data; the site publishes facts.

## Resources

### `GET /llms.txt`

Discovery file for agents.

It should list:

- canonical human pages
- `GET /agent/index.json`
- `GET /agent/snapshot.json`
- `GET /agent/spots/{slug}.json`
- optional `GET /agent/spots/{slug}.md`
- `GET /api/conditions` for the lower-level live condition feed

### `GET /agent/index.json`

Build-time generated catalog of all crawlable swim spots.

Shape:

```json
{
  "site": "Swim Francisco",
  "agent_data_version": 1,
  "generated_at": "2026-06-16T15:05:00Z",
  "local_timezone": "America/Los_Angeles",
  "spots": [
    {
      "slug": "aquatic-park",
      "name": "Aquatic Park",
      "type": "open_water",
      "canonical_url": "https://swimfrancisco.com/spots/aquatic-park/",
      "agent_json": "https://swimfrancisco.com/agent/spots/aquatic-park.json"
    }
  ]
}
```

### `GET /agent/spots/{slug}.json`

Build-time generated canonical detail record for one spot.

Includes:

- identity: slug, title, type, canonical URL
- location: address, lat/lng
- access: access mode, payment model, pricing, access notes
- schedules: pool sessions, closures, effective dates, verification dates
- open-water metadata: hazards, common distances, clubs, station IDs
- source URLs from frontmatter
- body summary or body Markdown
- links to live condition resources where applicable

This endpoint should not include hourly condition values unless they are
embedded from a separately generated snapshot. Static spot detail should
remain a build artifact.

### `GET /agent/spots/{slug}.md`

Optional build-time generated Markdown representation of the same detail
record.

Use this for agent tools that prefer text. It should include YAML
frontmatter with stable identifiers and a concise body with sections for
access, schedule, conditions link, hazards, and sources.

### `GET /agent/snapshot.json`

Runtime Worker-rendered answer surface for "right now" queries.

It combines:

- a generated static spot manifest bundled with the Worker at build time
- computed pool/access status and next change
- latest KV-backed condition records from `/api/conditions`

Shape:

```json
{
  "agent_data_version": 1,
  "generated_at": "2026-06-16T15:05:00Z",
  "local_time": "2026-06-16T08:05:00-07:00",
  "local_timezone": "America/Los_Angeles",
  "static_data_version": "bulletin-2026-06-16-001",
  "conditions_updated_at": "2026-06-16T15:00:00Z",
  "spots": [
    {
      "slug": "hamilton-pool",
      "name": "Hamilton Pool",
      "type": "pool",
      "status": "open",
      "next_change_at": "2026-06-16T15:00:00-07:00",
      "next_change_label": "closes at 15:00",
      "canonical_url": "https://swimfrancisco.com/spots/hamilton-pool/",
      "sources": [
        {
          "kind": "pool_schedule",
          "url": "https://sfrecpark.org/...",
          "last_verified_at": "2026-04-16"
        }
      ]
    },
    {
      "slug": "aquatic-park",
      "name": "Aquatic Park",
      "type": "open_water",
      "status": "access_open",
      "water_temp_f": 58.1,
      "water_temp_c": 14.5,
      "temp_observed_at": "2026-06-16T14:42:00Z",
      "temp_stale": false,
      "tide": {
        "station_id": "9414290",
        "predictions": [
          {
            "time": "2026-06-16T14:35:00",
            "type": "L",
            "value_ft": 0.7
          }
        ]
      },
      "canonical_url": "https://swimfrancisco.com/spots/aquatic-park/",
      "sources": [
        {
          "kind": "NOAA",
          "station_id": "9414290"
        }
      ]
    }
  ]
}
```

The snapshot owns computed `status`, `next_change_at`, and
`next_change_label`. Agents may inspect raw schedules in per-spot JSON,
but they should not need to reimplement timezone, closure, session, or
open-water access logic for common "right now" answers.

`next_change_at` is the machine-readable field. `next_change_label` is
display copy for clients that want Swim Francisco's wording. Agents
should not parse `next_change_label`.

The snapshot must not ship with a second implementation of status logic.
Before this endpoint is implemented, move the pure schedule/status
computation into a shared module that can be consumed by both browser JS
and the Worker, or choose a simpler snapshot that omits computed status
until that sharing is done.

## Update Model

Agent Data Mode has two update paths.

### Static spot facts

Facts from `content/spots/*.md` update during the existing site build:

```text
content/spots/*.md
        |
npm run build
        |
public/agent/index.json
public/agent/spots/{slug}.json
```

This covers names, addresses, schedules, closures, access rules,
pricing, source URLs, hazards, station IDs, and localized copy.

When a schedule extraction PR or manual content edit changes spot
frontmatter, the human pages and agent spot files change in the same
deploy.

### Live condition facts

NOAA / NDBC facts continue to update through the Worker cron:

```text
hourly cron
        |
NOAA / NDBC fetch
        |
KV conditions record
        |
GET /agent/snapshot.json
```

No deploy is needed for hourly water temperature or tide updates. The
Worker reads KV and renders the snapshot on request.

## Rendering Model

Build-time generated:

- `/agent/index.json`
- `/agent/spots/{slug}.json`
- optional `/agent/spots/{slug}.md`

Runtime Worker-rendered:

- `/agent/snapshot.json`

The Worker should import a compact generated spot manifest at build time.
That keeps snapshot generation local, avoids a runtime fetch to the
site's own assets, and makes the Worker deploy atomic with the static
content it summarizes. If the Workers Builds asset model makes that
awkward in practice, revisit this decision before implementing
`/agent/snapshot.json`.

## Freshness And Caching

Recommended headers:

```http
Content-Signal: ai-input=yes, search=yes, ai-train=no
X-Agent-Data-Version: 1
```

Static resources:

```http
Cache-Control: public, max-age=3600
```

Runtime snapshot:

```http
Cache-Control: public, max-age=60
```

Every response body should include enough timestamps for agents to
report freshness without trusting cache headers alone:

- `generated_at`
- `static_data_version`, preferably the build commit SHA
- `conditions_updated_at`
- per-source `last_verified_at`, `observed_at`, or `updated_at`
- stale flags from `/api/conditions`

The short snapshot cache is intentional. Conditions refresh hourly, but
pool status can change at any scheduled session boundary.

## Content Negotiation

JSON is the primary contract for v1.

Markdown can be served either as explicit `.md` resources or through
content negotiation:

```http
Accept: text/markdown
```

Content negotiation is deferred until explicit JSON resources are
stable. Explicit `.json` and `.md` URLs are easier for agents to
discover from `llms.txt`, logs, and copied citations.

## Source Attribution

Agent resources must preserve source boundaries:

- pool schedules come from reviewed source frontmatter and official
  source URLs
- open-water temperature and tide data come from NOAA / NDBC station
  records
- access/pricing rules come from spot frontmatter and linked source URLs
- stale condition values must be marked with existing stale and
  carried-since fields

Agents should be able to say "the schedule was last verified on X" or
"the water temperature was observed at Y from NOAA station Z" from the
payload alone.

## Locales

The default agent contract is English.

Localized agent resources may be added later using the same language
paths already generated for the human site, but v1 should not multiply
the endpoint surface before the English contract is stable.

## Implementation Slices

1. Update `static/llms.txt` to advertise the agent resources.
2. Generate `/agent/index.json` and `/agent/spots/{slug}.json` from
   existing spot frontmatter during `npm run build`.
3. Move pure status computation into a shared JS module usable by both
   browser code and the Worker.
4. Add `/agent/snapshot.json` in the Worker by combining the generated
   spot manifest, shared status computation, and KV conditions.
5. Add Markdown detail resources after the JSON contract is stable.
6. Consider `Accept: text/markdown` after explicit `.md` resources
   exist.

Do not advertise `agent_markdown` links in `/agent/index.json` until the
corresponding `.md` files exist.

## Avoid

- Do not make agents scrape the rendered board.
- Do not require JavaScript execution.
- Do not put all data into `llms.txt`.
- Do not introduce an MCP server until plain HTTP resources prove
  insufficient.
- Do not store duplicate agent-only facts that can drift from the human
  site.
- Do not hide source or freshness metadata behind prose.

## Open Questions

- Should `/agent/snapshot.json` include only board-level fields, or also
  enough detail to answer most one-shot questions without per-spot
  follow-up requests?

## Failure Behavior

- Unknown spot slugs return `404`.
- `/agent/index.json` and `/agent/spots/{slug}.json` are static build
  artifacts; missing files are deploy/build failures.
- `/agent/snapshot.json` returns `200` with partial records when KV
  conditions are missing but static spot data is available. Open-water
  condition fields should be `null`, stale flags should be false unless
  reused values are present, and `conditions_updated_at` should be null.
- `/agent/snapshot.json` returns `503` only when the Worker cannot read
  required static manifest data or another boundary failure prevents a
  trustworthy partial response.
- Agent JSON endpoints should use the same CORS policy as
  `/api/conditions`.
