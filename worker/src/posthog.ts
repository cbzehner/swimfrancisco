// Reverse proxy for PostHog (US cloud), exposed at /ingest/* on our own
// origin so adblockers can't block analytics. The browser snippet sets
// `api_host: '<base_url>/ingest'`; PostHog then builds every request under
// that prefix. We strip `/ingest` and forward to the matching PostHog host:
//   /ingest/static/*  → us-assets.i.posthog.com  (the JS library, cacheable)
//   /ingest/*         → us.i.posthog.com         (event ingestion, POST)
// Mirrors PostHog's official Cloudflare Worker proxy recipe.

const API_HOST = "us.i.posthog.com";
const ASSET_HOST = "us-assets.i.posthog.com";
const PREFIX = "/ingest";

// Library assets are immutable per version; cache them at the edge so the
// proxy doesn't round-trip to PostHog on every page load.
async function proxyStatic(request: Request, path: string, ctx: ExecutionContext): Promise<Response> {
  const cache = caches.default;
  const cacheKey = new Request(new URL(request.url).toString(), request);
  const cached = await cache.match(cacheKey);
  if (cached) return cached;

  const response = await fetch(`https://${ASSET_HOST}${path}`);
  ctx.waitUntil(cache.put(cacheKey, response.clone()));
  return response;
}

// Event ingestion: forward method, body, and query string verbatim. Drop the
// cookie header so we never leak our origin's cookies to PostHog.
async function proxyApi(request: Request, path: string): Promise<Response> {
  const forwarded = new Request(`https://${API_HOST}${path}`, request);
  forwarded.headers.delete("cookie");
  return fetch(forwarded);
}

export function isPosthogPath(path: string): boolean {
  return path === PREFIX || path.startsWith(PREFIX + "/");
}

export function handlePosthog(request: Request, ctx: ExecutionContext): Promise<Response> {
  const url = new URL(request.url);
  // Strip the `/ingest` prefix; `pathname + search` is what PostHog expects.
  const downstream = url.pathname.slice(PREFIX.length) + url.search;
  if (downstream.startsWith("/static/")) {
    return proxyStatic(request, downstream, ctx);
  }
  return proxyApi(request, downstream);
}
