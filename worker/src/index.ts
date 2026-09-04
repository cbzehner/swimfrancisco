// Swim Francisco conditions Worker.
// - Cron (hourly): walk each open-water spot's temp-source chain (USGS,
//   NOAA, NDBC, ERDDAP, MUR SST) and NOAA tide predictions; assemble
//   per-spot records; write KV. The 00:00 PT tick also triggers a rebuild.
// - HTTP: GET /api/conditions → slug-keyed bulk record from KV.
// - HTTP: /ingest/* → PostHog reverse proxy.

import { assembleAndPersist } from "./assemble.ts";
import { readConditionsRaw } from "./kv.ts";
import { corsHeaders, preflight } from "./cors.ts";
import { triggerRebuild } from "./deploy.ts";
import { isPtMidnight } from "./schedule.ts";
import { handlePosthog, isPosthogPath } from "./posthog.ts";

export interface Env {
  CONDITIONS: KVNamespace;
  WORKERS_BUILDS_DEPLOY_HOOK: string;
}

// Data refreshes hourly via cron. The Worker writes successful conditions
// responses to caches.default on miss, so most fetches in a given colo are
// served straight from the edge without re-reading KV. The cached response is
// header-neutral (no CORS); corsHeaders(request) is applied per-request after
// cache.match, so correctness never depends on the Cache API honoring Vary.
const JSON_CACHE_CONTROL = "public, max-age=900, s-maxage=3600";
const NEGATIVE_CACHE_CONTROL = "public, max-age=60";

// Canonical URL used as the Cache API key. Decouples the cache key from the
// incoming request's URL shape (trailing slashes, etc.).
const CONDITIONS_CACHE_KEY_URL = "https://swimfrancisco.com/api/conditions";

function withCors(request: Request, response: Response): Response {
  const out = new Response(response.body, response);
  for (const [name, value] of Object.entries(corsHeaders(request))) {
    out.headers.set(name, value);
  }
  return out;
}

function notFound(request: Request, message: string): Response {
  return new Response(message, {
    status: 404,
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": NEGATIVE_CACHE_CONTROL,
      ...corsHeaders(request),
    },
  });
}

function serviceUnavailable(request: Request, message: string): Response {
  return new Response(message, {
    status: 503,
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": NEGATIVE_CACHE_CONTROL,
      ...corsHeaders(request),
    },
  });
}

async function handleConditions(
  request: Request,
  env: Env,
  ctx: ExecutionContext,
): Promise<Response> {
  const cache = caches.default;
  const cacheKey = new Request(CONDITIONS_CACHE_KEY_URL);

  const cached = await cache.match(cacheKey);
  if (cached) return withCors(request, cached);

  let raw: string | null;
  try {
    raw = await readConditionsRaw(env.CONDITIONS);
  } catch (err) {
    console.error("KV read failed:", err);
    return serviceUnavailable(request, "conditions temporarily unavailable");
  }
  if (!raw) return serviceUnavailable(request, "conditions not yet available");

  const response = new Response(raw, {
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": JSON_CACHE_CONTROL,
    },
  });
  ctx.waitUntil(cache.put(cacheKey, response.clone()));
  return withCors(request, response);
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    // Analytics proxy is same-origin and forwards every method (POST for
    // ingestion, GET for the library), so it runs before the OPTIONS/GET
    // gate below, which only governs the JSON API.
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "");

    if (isPosthogPath(url.pathname)) {
      return handlePosthog(request, ctx);
    }

    if (path === "/api/conditions") {
      if (request.method === "OPTIONS") return preflight(request);
      if (request.method !== "GET") {
        return new Response("method not allowed", {
          status: 405,
          headers: { "content-type": "text/plain; charset=utf-8", ...corsHeaders(request) },
        });
      }
      return handleConditions(request, env, ctx);
    }

    return notFound(request, "not found");
  },

  async scheduled(event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    // Every hourly tick refreshes data. The tick that lands at 00:00 PT
    // also triggers a rebuild so the day-of-week rendered in static HTML
    // turns over with the calendar day. PT midnight maps to exactly one
    // UTC hour per day (DST-aware via Intl), so the rebuild fires once.
    ctx.waitUntil(
      assembleAndPersist(env.CONDITIONS).catch((err) => {
        console.error("assembleAndPersist failed:", err);
      }),
    );

    if (isPtMidnight(event.scheduledTime)) {
      ctx.waitUntil(
        triggerRebuild(env.WORKERS_BUILDS_DEPLOY_HOOK, event.scheduledTime).catch((err) => {
          console.error("triggerRebuild failed:", err);
        }),
      );
    }
  },
} satisfies ExportedHandler<Env>;
