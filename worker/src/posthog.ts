// Reverse proxy for PostHog (US cloud), exposed at /ingest/* on our own
// origin so adblockers can't block analytics. The browser snippet sets
// `api_host: '/ingest'`; PostHog then builds every request under that
// prefix. We strip `/ingest` and forward to the matching PostHog host:
//   /ingest/static/* , /ingest/array/*  → us-assets.i.posthog.com  (cacheable)
//   /ingest/*                           → us.i.posthog.com         (events, POST)
// Mirrors PostHog's official Cloudflare Worker proxy recipe.

const API_HOST = "us.i.posthog.com";
const ASSET_HOST = "us-assets.i.posthog.com";
const PREFIX = "/ingest";

// The JS library (/static/*) and remote config (/array/*) are cacheable and
// served from PostHog's asset host. Everything else is event ingestion.
function isAssetPath(path: string): boolean {
  return path.startsWith("/static/") || path.startsWith("/array/");
}

// Cache assets at the edge so the proxy doesn't round-trip to PostHog on every
// page load. cache.put honors the response's Cache-Control for TTL.
async function proxyAsset(request: Request, path: string, ctx: ExecutionContext): Promise<Response> {
  const cache = caches.default;
  const cacheKey = new Request(new URL(request.url).toString(), request);
  const cached = await cache.match(cacheKey);
  if (cached) return cached;

  const response = await fetch(`https://${ASSET_HOST}${path}`);
  ctx.waitUntil(cache.put(cacheKey, response.clone()));
  return response;
}

// Event ingestion. Drop the cookie header so we never leak our origin's
// cookies to PostHog, and forward the real client IP as X-Forwarded-For so
// PostHog's GeoIP resolves the visitor — not the Cloudflare edge that issues
// this subrequest. Buffer the body; forwarding the raw stream can drop data.
async function proxyApi(request: Request, path: string): Promise<Response> {
  const headers = new Headers(request.headers);
  headers.delete("cookie");
  const clientIp = request.headers.get("CF-Connecting-IP");
  if (clientIp) headers.set("X-Forwarded-For", clientIp);

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  return fetch(`https://${API_HOST}${path}`, {
    method: request.method,
    headers,
    body: hasBody ? await request.arrayBuffer() : undefined,
  });
}

export function isPosthogPath(path: string): boolean {
  return path === PREFIX || path.startsWith(PREFIX + "/");
}

export function handlePosthog(request: Request, ctx: ExecutionContext): Promise<Response> {
  const url = new URL(request.url);
  // Strip the `/ingest` prefix; `pathname + search` is what PostHog expects.
  const downstream = url.pathname.slice(PREFIX.length) + url.search;
  if (isAssetPath(downstream)) {
    return proxyAsset(request, downstream, ctx);
  }
  return proxyApi(request, downstream);
}
