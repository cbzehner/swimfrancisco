export interface Env {
  CONDITIONS: KVNamespace;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    return new Response("SwimFrancisco conditions worker. Implemented in Step 15.", {
      status: 200,
      headers: { "content-type": "text/plain" },
    });
  },

  async scheduled(event: ScheduledEvent, env: Env, ctx: ExecutionContext): Promise<void> {
    // Populated in Step 15 (NOAA 9414290 + NDBC 46237 fetches, KV writes).
  },
} satisfies ExportedHandler<Env>;
