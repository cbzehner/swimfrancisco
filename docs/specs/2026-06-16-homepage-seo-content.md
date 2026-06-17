# Homepage SEO Content - Deferred Spec

**Date:** 2026-06-16
**Status:** Deferred

## Context

Swim Francisco is crawlable and already has a technical SEO baseline:
canonical URLs, sitemap, robots.txt, `llms.txt`, homepage metadata,
spot-page JSON-LD, and spot breadcrumbs.

The weaker surface is the homepage body. It behaves like a live app and
does not visibly answer the broad discovery query "where to swim in San
Francisco" as directly as the metadata does. The board is useful and
crawlable, but it has little explanatory copy or internal grouping
context around it.

This spec records a future SEO/content pass. It should not block Agent
Data Mode work.

## Goals

- Make the homepage visibly answer "where to swim in San Francisco
  today" without turning it into a generic guide article.
- Give crawlers and agents a clearer machine-readable list of places on
  the homepage.
- Expose source and freshness signals more clearly.
- Reuse generated spot data where possible instead of creating a
  separate SEO-only data path.

## Non-goals

- No new guide pages in this slice.
- No keyword-stuffed copy.
- No hidden text or structured data that is not represented by visible
  page content.
- No changes to Agent Data Mode endpoint names.
- No dynamic status snapshot work. `/agent/snapshot.json` remains gated
  on shared status logic in the Agent Data Mode decision.

## Recommended Work

### 1. Add a compact homepage intro

Add a short visible section under the hero or just above the board.

Copy direction:

```text
Where to swim in San Francisco today

Swim Francisco tracks public pools, lap swim, family swim, membership
pools, beaches, and open-water swim spots across San Francisco. Use the
board to find what is open now, compare access rules, check water
temperature, and jump to official schedule sources.
```

Keep it compact and visually subordinate to the board. The product
should still feel like a live departure board, not a blog post.

### 2. Add homepage `ItemList` JSON-LD

Add a homepage-level `ItemList` structured-data block for the visible
spot list.

The list should use the same spot data as the rendered board and should
only include facts visible on the page or linked canonical spot pages.
Per-spot JSON-LD remains on spot pages.

If Agent Data Mode has already generated a static spot manifest, reuse
that source. Do not create a second SEO-only manifest.

### 3. Add accurate sitemap freshness

Make sitemap `<lastmod>` render for pages where the project has an
accurate significant-update date.

For spot pages, prefer the latest meaningful content/schedule freshness
signal, such as:

- `last_verified_at`
- `schedule_effective`
- a future explicit page update date if one is added

Do not emit guessed `lastmod` values. Inaccurate freshness is worse than
omitting the field.

### 4. Strengthen thin spot-page prose

For high-value or thin spot pages, add one or two concise paragraphs
that answer:

- who should swim there
- public, member, day-pass, or limited access
- neighborhood or location context
- lap, family, senior, pool, beach, or open-water relevance
- source and freshness cues

Prioritize pages with useful structured data but little body prose.

### 5. Add visible homepage groupings

Add a compact grouping surface that links into existing pages or filter
states:

- Public pools
- Lap swim
- Family swim
- Open-water spots
- Day-pass or membership pools

This should provide internal-link context without adding new pages.

## Relationship To Agent Data Mode

This work is aligned with Agent Data Mode but separate from it.

Shared principles:

- make the answer explicit
- expose source and freshness
- avoid asking agents or crawlers to infer facts from UI behavior
- reuse canonical spot data

Potential shared implementation:

- a generated spot manifest can feed both homepage `ItemList` JSON-LD
  and `/agent/index.json`
- spot detail fields such as access summary, last verified date,
  official source URL, and short description should be useful to both
  SEO and agent resources

Do not rename Agent Data Mode endpoints to `/spots.json` for SEO. Keep
`/agent/index.json` and `/agent/spots/{slug}.json` as the explicit agent
contract. A shorter `/spots.json` alias can be reconsidered later if a
real consumer needs it.

## Priority

1. Homepage intro.
2. Homepage `ItemList` JSON-LD.
3. Accurate sitemap `lastmod`.
4. Spot-page prose pass.
5. Homepage groupings.

## Deferral Notes

This is deferred until there is appetite for a focused SEO/content pass.
When picked up, keep the first slice small: intro copy plus ItemList
JSON-LD are the highest-leverage changes.
