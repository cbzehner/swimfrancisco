// Swim Francisco mobile tap-to-expand (Step 16).
//
// On narrow viewports (<=640px) the board hides TYPE and NEXT columns (see
// sass/main.scss responsive block). To keep the condensed row useful, tapping
// anywhere on a row — except the SPOT link itself — toggles an expanded
// sibling <tr class="row-detail"> showing the full destination link and the
// STATUS/NEXT values. Tapping the anchor still navigates to /spots/:slug/.
//
// Contract with main.scss:
//   - `.row-detail { display: none }` by default (already present).
//   - `tbody tr[aria-expanded="true"] + tr.row-detail { display: table-row }`
//     inside the (max-width:640px) block (already present). Desktop users
//     never see the injected row even if expanded, so the desktop anchor
//     behavior is unaffected.
//
// No frameworks, progressive enhancement: without JS the row simply does
// not expand; the SPOT link still navigates to the detail page.
//
// Script is idempotent — re-running init() would re-bind, but the module
// only runs once on DOMContentLoaded.

const MOBILE_QUERY = "(max-width: 640px)";

// Build the detail cell content from the row's existing data.
function buildDetailContent(row) {
  const slug = row.getAttribute("data-slug") || "";
  const spotAnchor = row.querySelector("td:first-child a");
  const spotHref = spotAnchor ? spotAnchor.getAttribute("href") : `/spots/${slug}/`;
  const spotText = spotAnchor ? spotAnchor.textContent.trim() : slug;
  const cells = row.querySelectorAll("td");
  const statusText = cells[2] ? cells[2].textContent.trim() : "";
  const nextText = cells[3] ? cells[3].textContent.trim() : "";

  const fragment = document.createDocumentFragment();

  if (statusText && statusText !== "—") {
    const statusLine = document.createElement("div");
    statusLine.textContent = `STATUS: ${statusText}`;
    fragment.appendChild(statusLine);
  }
  if (nextText && nextText !== "—") {
    const nextLine = document.createElement("div");
    nextLine.textContent = `NEXT: ${nextText}`;
    fragment.appendChild(nextLine);
  }

  const linkLine = document.createElement("div");
  const link = document.createElement("a");
  link.href = spotHref;
  link.textContent = `Details for ${spotText} →`;
  linkLine.appendChild(link);
  fragment.appendChild(linkLine);

  return fragment;
}

// Insert (or replace) the .row-detail sibling after the row.
function insertDetailRow(row) {
  removeDetailRow(row);
  const detail = document.createElement("tr");
  detail.className = "row-detail";
  const cell = document.createElement("td");
  // Board has 5 columns; use colspan 5 so the detail spans the whole row.
  cell.colSpan = 5;
  cell.appendChild(buildDetailContent(row));
  detail.appendChild(cell);
  row.parentNode.insertBefore(detail, row.nextSibling);
}

// Remove the injected .row-detail sibling if present.
function removeDetailRow(row) {
  const next = row.nextElementSibling;
  if (next && next.classList.contains("row-detail")) {
    next.remove();
  }
}

function collapseAll(tbody) {
  tbody.querySelectorAll('tr[aria-expanded="true"]').forEach((row) => {
    row.setAttribute("aria-expanded", "false");
    removeDetailRow(row);
  });
}

function handleRowClick(event, tbody, mql) {
  // Desktop: do nothing — the anchor in the SPOT cell handles navigation.
  if (!mql.matches) return;

  const row = event.target.closest("tbody tr");
  if (!row || row.classList.contains("row-detail")) return;

  // Let the SPOT anchor (or any anchor inside) handle its own click.
  if (event.target.closest("a")) return;

  const expanded = row.getAttribute("aria-expanded") === "true";
  if (expanded) {
    row.setAttribute("aria-expanded", "false");
    removeDetailRow(row);
  } else {
    collapseAll(tbody);
    row.setAttribute("aria-expanded", "true");
    insertDetailRow(row);
  }
}

function init() {
  const tbody = document.querySelector("table.board tbody");
  if (!tbody) return;
  const mql = window.matchMedia(MOBILE_QUERY);

  tbody.addEventListener("click", (event) => handleRowClick(event, tbody, mql));

  // If the viewport crosses the breakpoint upward, collapse everything so
  // the desktop layout is not left with stale injected rows.
  const onChange = () => {
    if (!mql.matches) collapseAll(tbody);
  };
  mql.addEventListener("change", onChange);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
