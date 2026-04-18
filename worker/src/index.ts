// SwimFrancisco conditions Worker.
// - Cron (hourly): fetch NOAA 9414290 + fallback 9414750 (bay temp + tides)
//   and NDBC 46237 (ocean temp); assemble per-spot records; write KV.
// - HTTP: GET /api/conditions → bulk `all`; GET /api/conditions/:slug → spot.

import { assembleAndPersist } from "./assemble";
import { readAllRaw, readSpotRaw } from "./kv";
import { corsHeaders, preflight } from "./cors";

export interface Env {
  CONDITIONS: KVNamespace;
}

// Data refreshes hourly via cron; bound clients to 5min and edge to 15min.
const JSON_CACHE_CONTROL = "public, max-age=300, s-maxage=900";
const NEGATIVE_CACHE_CONTROL = "public, max-age=60";

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

async function handleAll(request: Request, env: Env): Promise<Response> {
  const raw = await readAllRaw(env.CONDITIONS);
  if (!raw) return serviceUnavailable(request, "conditions not yet available");
  return jsonResponse(request, raw);
}

async function handleSpot(request: Request, env: Env, slug: string): Promise<Response> {
  const raw = await readSpotRaw(env.CONDITIONS, slug);
  if (!raw) return notFound(request, `no conditions for slug ${slug}`);
  return jsonResponse(request, raw);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
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
      return handleAll(request, env);
    }

    const spotMatch = path.match(/^\/api\/conditions\/([a-z0-9-]+)$/);
    if (spotMatch) {
      return handleSpot(request, env, spotMatch[1]);
    }

    return notFound(request, "not found");
  },

  async scheduled(_event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(
      assembleAndPersist(env.CONDITIONS).catch((err) => {
        console.error("assembleAndPersist failed:", err);
      }),
    );
  },
} satisfies ExportedHandler<Env>;
