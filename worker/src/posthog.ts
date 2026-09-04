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
const MAX_API_BODY_BYTES = 1024 * 1024;

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
// Enforce the limit while reading because Content-Length can be absent or incorrect.
async function readApiBody(request: Request): Promise<ArrayBuffer | null> {
  const declaredLength = Number(request.headers.get("content-length"));
  if (Number.isFinite(declaredLength) && declaredLength > MAX_API_BODY_BYTES) {
    if (request.body) await request.body.cancel().catch(() => undefined);
    return null;
  }
  if (!request.body) return new ArrayBuffer(0);

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let totalBytes = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      totalBytes += value.byteLength;
      if (totalBytes > MAX_API_BODY_BYTES) {
        await reader.cancel().catch(() => undefined);
        return null;
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }

  const body = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body.buffer;
}

async function proxyApi(request: Request, path: string): Promise<Response> {
  const headers = new Headers(request.headers);
  headers.delete("cookie");
  headers.delete("content-length");
  headers.delete("transfer-encoding");
  const clientIp = request.headers.get("CF-Connecting-IP");
  if (clientIp) headers.set("X-Forwarded-For", clientIp);

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const body = hasBody ? await readApiBody(request) : undefined;
  if (body === null) {
    return new Response("analytics payload too large", {
      status: 413,
      headers: {
        "cache-control": "no-store",
        "content-type": "text/plain; charset=utf-8",
      },
    });
  }
  return fetch(`https://${API_HOST}${path}`, {
    method: request.method,
    headers,
    body,
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
