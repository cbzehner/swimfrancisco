// Swim Francisco conditions Worker.
// - Cron (hourly): fetch NOAA 9414290 + fallback 9414750 (bay temp + tides)
//   and NDBC 46237 (ocean temp); assemble per-spot records; write KV.
// - HTTP: GET /api/conditions → slug-keyed bulk record from KV.

import { assembleAndPersist } from "./assemble";
import { readConditionsRaw } from "./kv";
import { corsHeaders, preflight } from "./cors";
import { triggerRebuild } from "./deploy";
import { isPtMidnight } from "./schedule";

export interface Env {
  CONDITIONS: KVNamespace;
  WORKERS_BUILDS_DEPLOY_HOOK: string;
}

// Data refreshes hourly via cron. The Worker writes successful conditions
// responses to caches.default on miss, so most fetches in a given colo are
// served straight from the edge without re-reading KV. Vary: Origin (set in
// corsHeaders) gives each allowed origin its own cache entry.
const JSON_CACHE_CONTROL = "public, max-age=900";
const NEGATIVE_CACHE_CONTROL = "public, max-age=60";

// Canonical URL used as the Cache API key. Decouples the cache key from the
// incoming request's URL shape (trailing slashes, etc.).
const CONDITIONS_CACHE_KEY_URL = "https://swimfrancisco.com/api/conditions";

function jsonResponse(request: Request, body: string, status = 200): Response {
  return new Response(body, {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": JSON_CACHE_CONTROL,
      ...corsHeaders(request),
    },
  });
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
  // Inheriting headers from `request` preserves the Origin used for Vary keying.
  const cacheKey = new Request(CONDITIONS_CACHE_KEY_URL, request);

  const cached = await cache.match(cacheKey);
  if (cached) return cached;

  const raw = await readConditionsRaw(env.CONDITIONS);
  if (!raw) return serviceUnavailable(request, "conditions not yet available");

  const response = jsonResponse(request, raw);
  ctx.waitUntil(cache.put(cacheKey, response.clone()));
  return response;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (request.method === "OPTIONS") return preflight(request);

    if (request.method !== "GET") {
      return new Response("method not allowed", {
        status: 405,
        headers: { "content-type": "text/plain; charset=utf-8", ...corsHeaders(request) },
      });
    }

    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "");

    if (path === "/api/conditions") {
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
