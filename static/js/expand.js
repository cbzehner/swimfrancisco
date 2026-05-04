// Swim Francisco row navigation: clicking anywhere on a board row navigates
// to the spot detail page. The SPOT cell still contains a real <a> so right-
// click / "open in new tab" / keyboard focus all work; this handler just
// extends the click target to the rest of the row.

function handleRowClick(event) {
  const row = event.target.closest("tbody tr");
  if (!row) return;
  if (event.target.closest("a")) return;

  const anchor = row.querySelector("td:first-child a");
  const href = anchor && anchor.getAttribute("href");
  if (!href) return;

  if (event.metaKey || event.ctrlKey || event.shiftKey || event.button === 1) {
    window.open(href, "_blank");
  } else {
    window.location.href = href;
  }
}

function init() {
  const tbody = document.querySelector("table.board tbody");
  if (!tbody) return;
  tbody.addEventListener("click", handleRowClick);
  tbody.addEventListener("auxclick", (event) => {
    if (event.button === 1) handleRowClick(event);
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
