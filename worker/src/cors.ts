// CORS helper — only swimfrancisco.com is allowed.
const ALLOW_ORIGIN = "https://swimfrancisco.com";

export function corsHeaders(): Record<string, string> {
  return {
    "access-control-allow-origin": ALLOW_ORIGIN,
    "access-control-allow-methods": "GET, OPTIONS",
    "access-control-allow-headers": "content-type",
    "access-control-max-age": "86400",
    vary: "Origin",
  };
}

export function preflight(): Response {
  return new Response(null, { status: 204, headers: corsHeaders() });
}
