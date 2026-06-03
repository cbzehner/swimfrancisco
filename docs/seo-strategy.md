# Google SEO Strategy

Swim Francisco should rank by being the fastest, clearest answer to local swim-intent searches, not by publishing broad generic swim content.

## Search Intent

- **Primary query:** "where to swim in San Francisco right now"
- **Long-tail pool queries:** "`<pool name>` swim schedule", "`<pool name>` lap swim", "`<pool name>` family swim", "`<pool name>` hours"
- **Open-water queries:** "Aquatic Park swim conditions", "San Francisco open water swim spots", "`<beach>` swimming hazards"
- **Discovery query:** "San Francisco swim map"

## Technical Baseline

Implemented:

- Page-specific `<title>` and meta descriptions for the board, map, pools, and open-water pages.
- Canonical URLs on every rendered page.
- Open Graph and Twitter summary metadata for share previews.
- `WebSite` JSON-LD on the home page.
- `SportsActivityLocation` or `Beach` JSON-LD on spot pages, limited to facts already visible on the page.
- `BreadcrumbList` JSON-LD on spot pages.
- Versioned `robots.txt` with a fully qualified sitemap URL.
- Explicit allow rules for major LLM search and fetch user agents, including `OAI-SearchBot`, `ChatGPT-User`, `PerplexityBot`, `Perplexity-User`, `Claude-SearchBot`, `Claude-User`, `Google-Extended`, and `Bingbot`.
- `llms.txt` as a markdown discovery index for AI agents and LLM-oriented crawlers.
- Render tests that parse generated JSON-LD and check canonical, robots, and sitemap output.

This follows Google Search Central guidance to make pages crawlable, use unique descriptions, canonicalize duplicate URLs, submit sitemaps, and keep structured data representative of visible page content:

- https://developers.google.com/search/docs/fundamentals/seo-starter-guide
- https://developers.google.com/search/docs/crawling-indexing
- https://developers.google.com/search/docs/appearance/structured-data/breadcrumb
- https://developers.google.com/search/docs/appearance/structured-data/sd-policies
- https://platform.openai.com/docs/bots
- https://docs.perplexity.ai/docs/resources/perplexity-crawlers
- https://support.claude.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler

## Content Strategy

1. Keep spot pages as the primary long-tail landing pages. Each page should answer schedule, access, location, source, and safety/context in the first screen.
2. Add concise body copy to thin membership/facility pages whose current value is mostly frontmatter. Prioritize pages already in the sitemap with no visible prose.
3. Add short evergreen explainers only when they support local swim decisions, for example:
   - "How public pool schedules work in San Francisco"
   - "Where to start open-water swimming in San Francisco"
   - "How to choose between lap swim, family swim, and senior swim"
4. Keep field-note/internal build content out of the production sitemap unless it becomes reader-facing.

## Search Console Workflow

1. Verify `https://swimfrancisco.com` in Google Search Console.
2. Submit `https://swimfrancisco.com/sitemap.xml`.
3. Inspect the home page, `/map/`, and three representative spot pages after deploy.
4. Track queries by page type:
   - Home: generic "swim San Francisco" and "where to swim" queries.
   - Map: map/discovery queries.
   - Spot pages: pool and beach name queries.
5. Revisit titles/descriptions only after impressions appear; do not churn metadata without query data.
6. Check server or Cloudflare logs for successful `OAI-SearchBot`, `ChatGPT-User`, `PerplexityBot`, `Perplexity-User`, `Claude-SearchBot`, `Claude-User`, `Googlebot`, and `Bingbot` requests. A permissive `robots.txt` is not enough if edge bot controls return 403 or challenges.

## Editorial Guardrails

- Do not add opening-hours structured data from swim sessions unless the data represents facility business hours.
- Do not add review/rating structured data unless Swim Francisco hosts first-party reviews.
- Do not hide keyword lists or add text that is not useful to swimmers.
- Prefer official source links and visible schedule dates over broad claims.
- Treat `llms.txt` as a discovery aid, not a substitute for crawlable HTML, sitemap coverage, canonical tags, or clear page copy.
