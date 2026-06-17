// Site-wide chrome interactions, loaded on every page from base.html.
// Currently records language switches: the destination $pageview already
// reveals the new locale, but a first-class event lets us measure real demand
// per locale and build a switch funnel. Capture is a no-op without analytics.

import { capture } from "./helpers/analytics.mjs";

function initLanguageTracking() {
  const switcher = document.querySelector(".language-switcher");
  if (!switcher) return;
  switcher.addEventListener("click", (event) => {
    const link = event.target.closest("a[lang]");
    if (!link) return;
    capture("language_switched", {
      to: link.getAttribute("lang") || "",
      from: document.documentElement.lang || "",
    });
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initLanguageTracking);
} else {
  initLanguageTracking();
}
