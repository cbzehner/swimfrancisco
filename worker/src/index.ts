// Swim Francisco conditions Worker.
// - Cron (hourly): fetch NOAA 9414290 + fallback 9414750 (bay temp + tides)
//   and NDBC 46237 (ocean temp); assemble per-spot records; write KV.
// - HTTP: GET /api/conditions → slug-keyed bulk record from KV.

import { assembleAndPersist } from "./assemble";
import { readConditionsRaw } from "./kv";
import { corsHeaders, preflight } from "./cors";
import { triggerRebuild } from "./deploy";
import { classifyTick } from "./schedule";

export interface Env {
  CONDITIONS: KVNamespace;
  WORKERS_BUILDS_DEPLOY_HOOK: string;
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

async function handleConditions(request: Request, env: Env): Promise<Response> {
  const raw = await readConditionsRaw(env.CONDITIONS);
  if (!raw) return serviceUnavailable(request, "conditions not yet available");
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
      return handleConditions(request, env);
    }

    return notFound(request, "not found");
  },

  async scheduled(event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    // Daily rebuild: fires once per calendar day at 00:05 PT year-round.
    // Two daily crons in wrangler.toml cover PST (`5 8 UTC`) and PDT (`5 7 UTC`);
    // `classifyTick` gates on PT hour 0 + UTC minute 5 so the hourly cron
    // (minute 0) always falls through to the NOAA refresh path, including at
    // 00:00 PT. Dispatch logic lives in ./schedule.ts and is unit-tested.
    if (classifyTick(event.scheduledTime) === "rebuild") {
      ctx.waitUntil(
        triggerRebuild(env.WORKERS_BUILDS_DEPLOY_HOOK, event.scheduledTime).catch((err) => {
          console.error("triggerRebuild failed:", err);
        }),
      );
      return;
    }

    ctx.waitUntil(
      assembleAndPersist(env.CONDITIONS).catch((err) => {
        console.error("assembleAndPersist failed:", err);
      }),
    );
  },
} satisfies ExportedHandler<Env>;
