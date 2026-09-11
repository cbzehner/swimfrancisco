// Swim Francisco conditions Worker.
// - Cron (hourly): walk each open-water spot's temp-source chain (USGS,
//   NOAA, NDBC, ERDDAP, MUR SST) and NOAA tide predictions; assemble
//   per-spot records; write KV. The 00:00 PT tick also triggers a rebuild.
// - HTTP: GET /api/conditions → slug-keyed bulk record from KV.
// - HTTP: GET /api/map-config → public browser map configuration.
// - HTTP: /ingest/* → PostHog reverse proxy.

import { assembleAndPersist } from "./assemble.ts";
import { readConditionsRaw } from "./kv.ts";
import { triggerRebuild } from "./deploy.ts";
import { isPtMidnight } from "./schedule.ts";
import { handlePosthog, isPosthogPath } from "./posthog.ts";

export interface Env {
  CONDITIONS: KVNamespace;
  WORKERS_BUILDS_DEPLOY_HOOK: string;
  CARTO_BASEMAP_API_KEY?: string;
}

// Data refreshes hourly via cron. The Worker writes successful conditions
// responses to caches.default on miss, so most fetches in a given colo are
// served straight from the edge without re-reading KV.
const JSON_CACHE_CONTROL = "public, max-age=900, s-maxage=3600";
const NEGATIVE_CACHE_CONTROL = "public, max-age=60";

// Canonical URL used as the Cache API key. Decouples the cache key from the
// incoming request's URL shape (trailing slashes, etc.).
const CONDITIONS_CACHE_KEY_URL = "https://swimfrancisco.com/api/conditions";

// `cacheControl` is explicit per call site: the miss responses are worth
// caching briefly at the edge, a rejected method is not.
function errorResponse(status: number, message: string, cacheControl?: string): Response {
  const headers: Record<string, string> = { "content-type": "text/plain; charset=utf-8" };
  if (cacheControl) headers["cache-control"] = cacheControl;
  return new Response(message, { status, headers });
}

async function handleConditions(env: Env, ctx: ExecutionContext): Promise<Response> {
  const cache = caches.default;
  const cacheKey = new Request(CONDITIONS_CACHE_KEY_URL);

  const cached = await cache.match(cacheKey);
  if (cached) return cached;

  let raw: string | null;
  try {
    raw = await readConditionsRaw(env.CONDITIONS);
  } catch (err) {
    console.error("KV read failed:", err);
    return errorResponse(503, "conditions temporarily unavailable", NEGATIVE_CACHE_CONTROL);
  }
  if (!raw) return errorResponse(503, "conditions not yet available", NEGATIVE_CACHE_CONTROL);

  const response = new Response(raw, {
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": JSON_CACHE_CONTROL,
    },
  });
  ctx.waitUntil(cache.put(cacheKey, response.clone()));
  return response;
}

function handleMapConfig(request: Request, env: Env): Response {
  const headers = { "cache-control": "no-store" };
  if (request.method !== "GET") {
    return Response.json(
      { error: "method not allowed" },
      { status: 405, headers: { ...headers, allow: "GET" } },
    );
  }

  const cartoBasemapKey = env.CARTO_BASEMAP_API_KEY?.trim();
  if (!cartoBasemapKey) {
    return Response.json(
      { error: "map configuration unavailable" },
      { status: 503, headers },
    );
  }

  return Response.json({ carto_basemap_key: cartoBasemapKey }, { headers });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    // Analytics proxy is same-origin and forwards every method (POST for
    // ingestion, GET for the library), so it runs before the GET gate
    // below, which only governs the JSON API.
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "");

    if (isPosthogPath(url.pathname)) {
      return handlePosthog(request, ctx);
    }

    if (path === "/api/conditions") {
      if (request.method !== "GET") return errorResponse(405, "method not allowed");
      return handleConditions(env, ctx);
    }

    if (path === "/api/map-config") {
      return handleMapConfig(request, env);
    }

    return errorResponse(404, "not found", NEGATIVE_CACHE_CONTROL);
  },

  async scheduled(event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    // Every hourly tick refreshes data. The tick that lands at 00:00 PT
    // also triggers a rebuild so the day-of-week rendered in static HTML
    // turns over with the calendar day. PT midnight maps to exactly one
    // UTC hour per day (DST-aware via Intl), so the rebuild fires once.
    ctx.waitUntil(
      assembleAndPersist(env.CONDITIONS).catch((err) => {
        console.error("assembleAndPersist failed:", err);
        throw err;
      }),
    );

    if (isPtMidnight(event.scheduledTime)) {
      ctx.waitUntil(
        triggerRebuild(env.WORKERS_BUILDS_DEPLOY_HOOK, event.scheduledTime).catch((err) => {
          console.error("triggerRebuild failed:", err);
          throw err;
        }),
      );
    }
  },
} satisfies ExportedHandler<Env>;
