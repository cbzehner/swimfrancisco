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

const JSON_CACHE_CONTROL = "public, max-age=60, s-maxage=300";

function jsonResponse(body: string, status = 200): Response {
  return new Response(body, {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": JSON_CACHE_CONTROL,
      ...corsHeaders(),
    },
  });
}

function notFound(message: string): Response {
  return new Response(message, {
    status: 404,
    headers: { "content-type": "text/plain; charset=utf-8", ...corsHeaders() },
  });
}

function serviceUnavailable(message: string): Response {
  return new Response(message, {
    status: 503,
    headers: { "content-type": "text/plain; charset=utf-8", ...corsHeaders() },
  });
}

async function handleAll(env: Env): Promise<Response> {
  const raw = await readAllRaw(env.CONDITIONS);
  if (!raw) return serviceUnavailable("conditions not yet available");
  return jsonResponse(raw);
}

async function handleSpot(env: Env, slug: string): Promise<Response> {
  const raw = await readSpotRaw(env.CONDITIONS, slug);
  if (!raw) return notFound(`no conditions for slug ${slug}`);
  return jsonResponse(raw);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === "OPTIONS") return preflight();

    if (request.method !== "GET") {
      return new Response("method not allowed", {
        status: 405,
        headers: { "content-type": "text/plain; charset=utf-8", ...corsHeaders() },
      });
    }

    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "");

    if (path === "/api/conditions") {
      return handleAll(env);
    }

    const spotMatch = path.match(/^\/api\/conditions\/([a-z0-9-]+)$/);
    if (spotMatch) {
      return handleSpot(env, spotMatch[1]);
    }

    return notFound("not found");
  },

  async scheduled(_event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(
      assembleAndPersist(env.CONDITIONS).catch((err) => {
        console.error("assembleAndPersist failed:", err);
      }),
    );
  },
} satisfies ExportedHandler<Env>;
