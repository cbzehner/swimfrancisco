// Site-wide chrome interactions, loaded on every page from base.html.
// Currently records language switches: the destination $pageview already
// reveals the new locale, but a first-class event lets us measure real demand
// per locale and build a switch funnel. Capture is a no-op without analytics.

import { capture } from "./helpers/analytics.mjs";

export function mountChrome(root = document) {
  const controller = new AbortController();
  const switcher = root.querySelector(".language-switcher");
  switcher?.addEventListener("click", (event) => {
    const link = event.target.closest("a[lang]");
    if (!link) return;
    capture("language_switched", {
      to: link.getAttribute("lang") || "",
      from: document.documentElement.lang || "",
    });
  }, { signal: controller.signal });
  return { dispose() { controller.abort(); } };
}
