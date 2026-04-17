// CORS helper — allow production, Pages preview deploys, and localhost.
// Echo back the matched origin; omit ACAO entirely if origin doesn't match.

const ALLOW_PATTERNS: RegExp[] = [
  /^https:\/\/swimfrancisco\.com$/,
  /^https:\/\/([a-z0-9-]+\.)*swimfrancisco\.pages\.dev$/,
  /^http:\/\/localhost(:\d+)?$/,
];

export function isAllowedOrigin(origin: string | null): string | null {
  if (!origin) return null;
  return ALLOW_PATTERNS.some((re) => re.test(origin)) ? origin : null;
}

export function corsHeaders(request: Request): Record<string, string> {
  const matched = isAllowedOrigin(request.headers.get("origin"));
  const headers: Record<string, string> = {
    "access-control-allow-methods": "GET, OPTIONS",
    "access-control-allow-headers": "content-type",
    "access-control-max-age": "86400",
    vary: "Origin",
  };
  if (matched) {
    headers["access-control-allow-origin"] = matched;
  }
  return headers;
}

export function preflight(request: Request): Response {
  return new Response(null, { status: 204, headers: corsHeaders(request) });
}
