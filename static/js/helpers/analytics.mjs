// Thin wrapper over PostHog's `capture` for first-party product events.
//
// These custom events complement the autocapture defaults wired in
// base.html ($pageview, $autocapture, $pageleave, $web_vitals). Autocapture
// can see *that* something was clicked, but not the product meaning behind it
// — which program was filtered, which spot was opened, where an outbound link
// pointed. Those are the questions these events answer.
//
// `capture` is a no-op whenever analytics is unavailable: no PostHog key
// configured, an adblocker dropped the script, or the visitor never loaded
// it. The PostHog snippet installs a queueing stub synchronously, so calls
// made before array.js finishes loading are buffered, not lost. Callers never
// need to guard or await — fire and forget.
export function capture(event, properties = {}) {
  const posthog = typeof window !== "undefined" ? window.posthog : null;
  if (!posthog || typeof posthog.capture !== "function") return;
  try {
    posthog.capture(event, properties);
  } catch {
    // Analytics must never break the page.
  }
}
