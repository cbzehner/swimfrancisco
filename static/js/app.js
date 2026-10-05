import { mountSite } from "./site.js";

// The only auto-starting module. Cached pages retain their controls and map
// viewport; the browser freezes them until pageshow, when time is refreshed.
// A full exit disposes timers, requests, and listeners.
let site;
function start() { site ||= mountSite(); }
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
else start();
window.addEventListener("pagehide", (event) => {
  if (!event.persisted) { site?.dispose(); site = null; }
});
window.addEventListener("pageshow", (event) => {
  if (event.persisted && site) site.refresh();
  else start();
});
