// Board browser adapter. Catalog decoding happens at mount; all decisions
// come from evaluateBoard and transitionBoard, never from rendered cells.
import { OPEN_STATUSES, PLACEHOLDER, evaluateBoard, formatHHMM, getHorizonOptions,
  readNumberAttribute, readScheduleAttribute } from "./helpers/board.mjs";
import { initialBoardState, serializeBoardHash, transitionBoard } from "./helpers/board-state.mjs";
import { pacificWallClockDate } from "./helpers/pacific.mjs";
import { programLabel, statusLabel, statusNextLabel, t } from "./helpers/i18n.mjs";
import { capture } from "./helpers/analytics.mjs";
import { initHorizonMenu } from "./helpers/horizon-menu.mjs";

const HORIZON_TITLES = {
  "this-morning": ["horizon_fog_lift", "FOG-LIFT WINDOW"],
  "this-afternoon": ["horizon_lunch", "LUNCH BREAK LANES"],
  "this-evening": ["horizon_after_work", "AFTER-WORK WATER"],
  "tomorrow-morning": ["horizon_set_alarm", "SET THE ALARM"],
  "tomorrow-afternoon": ["horizon_clear_calendar", "CLEAR THE CALENDAR"],
  "tomorrow-evening": ["horizon_golden_hour", "GOLDEN HOUR TOMORROW"],
};

const HORIZON_LABEL_KEYS = {
  now: ["now", "Now"],
  "this-morning": ["horizon_this_morning", "This Morning"],
  "this-afternoon": ["horizon_this_afternoon", "This Afternoon"],
  "this-evening": ["horizon_this_evening", "This Evening"],
  "tomorrow-morning": ["horizon_tomorrow_morning", "Tomorrow Morning"],
  "tomorrow-afternoon": ["horizon_tomorrow_afternoon", "Tomorrow Afternoon"],
  "tomorrow-evening": ["horizon_tomorrow_evening", "Tomorrow Evening"],
};

function horizonLabel(horizon) {
  const [key, fallback] = HORIZON_LABEL_KEYS[horizon?.id] || [];
  return key ? t(key, fallback) : horizon?.label || "";
}

function currentTimeTitle(now) {
  const hour = now.getHours();
  if (hour < 5) return t("horizon_night_swim", "NIGHT SWIM");
  if (hour < 10) return t("horizon_before_breakfast", "BEFORE BREAKFAST");
  if (hour < 14) return t("horizon_lunch", "LUNCH BREAK LANES");
  if (hour < 17) return t("horizon_post_fog", "POST-FOG SWIM");
  if (hour < 21) return t("horizon_after_work", "AFTER-WORK WATER");
  return t("horizon_night_swim", "NIGHT SWIM");
}

function applyHorizonChrome(root, horizon, now) {
  const isNow = !horizon || horizon.id === "now";
  const titleSource = HORIZON_TITLES[horizon.id];
  const title = isNow
    ? currentTimeTitle(now)
    : titleSource
      ? t(titleSource[0], titleSource[1])
      : horizonLabel(horizon).toUpperCase();
  const label = horizonLabel(horizon);
  root.querySelectorAll("[data-horizon-title]").forEach((node) => {
    node.textContent = `·${title}·`;
  });
  root.querySelectorAll("[data-horizon-button]").forEach((node) => {
    node.textContent = isNow ? t("now", "Now") : label;
  });
  root.querySelectorAll("[data-horizon-stamp-label]").forEach((node) => {
    node.textContent = isNow ? t("open_now", "OPEN NOW") : label.toUpperCase();
  });

  const banner = root.querySelector("[data-time-banner]");
  if (!banner) return;
  banner.hidden = isNow;
  const bannerLabel = banner.querySelector("[data-time-banner-label]");
  if (bannerLabel) bannerLabel.textContent = isNow ? t("right_now", "Right now") : horizonLabel(horizon);
}

function formatWindowNext(result) {
  const session = result.bestWindow;
  if (!session) return statusNextLabel(result, PLACEHOLDER);
  const program = programLabel(session.type);
  return `${program} ${formatHHMM(session.start)}\u2013${formatHHMM(session.end)}`;
}

function cell(row, name) {
  return row.querySelector(`[data-cell="${name}"]`);
}

function statusClass(status, type) {
  if (type === "open_water" || status === "OCEAN") return "is-ocean";
  if (OPEN_STATUSES.has(status)) return "is-open";
  if (status === "CHECK") return "is-info";
  return "is-closed";
}

function setStatus(statusCell, status, type, sublabel = "") {
  let pill = statusCell.querySelector(".status-pill");
  if (!pill) {
    statusCell.textContent = "";
    pill = document.createElement("span");
    pill.className = "status-pill";
    statusCell.append(pill);
  }
  statusCell.dataset.statusValue = status;
  pill.textContent = statusLabel(status);
  pill.className = `status-pill ${statusClass(status, type)}`;

  let sub = statusCell.querySelector(".status-sub");
  if (sublabel) {
    if (!sub) {
      sub = document.createElement("span");
      sub.className = "status-sub";
      statusCell.append(sub);
    }
    sub.textContent = sublabel;
  } else if (sub) {
    sub.remove();
  }
}

// Whole-row navigation. The spot link's CSS overlay covers only its own cell
// (a row-wide overlay is impossible cross-engine: WebKit doesn't make
// <tr position:relative> a containing block, so it escaped the row and
// swallowed clicks on the controls). Clicks elsewhere on a row follow the
// row's spot link; real links/buttons and modified clicks pass through.
function initRowNavigation(tbody, signal, captureSpotOpened) {
  tbody.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (event.target.closest("a, button")) return;
    if (window.getSelection && String(window.getSelection())) return;
    const row = event.target.closest("tr");
    const href = row?.querySelector('[data-cell="spot"] a')?.getAttribute("href");
    if (href) {
      captureSpotOpened(row, "board_row");
      window.location.assign(href);
    }
  }, { signal });
  // Direct clicks on the spot link itself bypass the overlay branch above
  // (it ignores clicks on <a>), so capture those here. Modified/middle clicks
  // that open a new tab still register intent — that's worth counting.
  tbody.addEventListener("click", (event) => {
    const link = event.target.closest('[data-cell="spot"] a');
    if (link) captureSpotOpened(link.closest("tr"), "board_link");
  }, { signal });
}

function readSpots(rows) {
  return rows.map((row) => {
    const nameCell = cell(row, "spot");
    const link = nameCell?.querySelector("a");
    return {
      slug: row.dataset.slug || "", type: row.dataset.type || "pool",
      accessMode: row.dataset.accessMode || "public", schedule: readScheduleAttribute(row),
      name: link?.textContent.trim() || nameCell?.textContent.trim() || "",
      label: nameCell?.textContent.trim() || "", href: link?.getAttribute("href") || "",
      typeLabel: nameCell?.querySelector(".spot-subtitle")?.textContent.trim() || row.dataset.subtype || row.dataset.type || "",
      lat: readNumberAttribute(row, "data-lat"), lng: readNumberAttribute(row, "data-lng"),
    };
  });
}

function presentEntry(entry, horizon) {
  const { result } = entry;
  const nextText = entry.type === "open_water"
    ? horizon.kind === "window" ? t("status_check_conditions", "CHECK CONDITIONS") : PLACEHOLDER
    : horizon.kind === "window" && entry.sessionBased ? formatWindowNext(result) : statusNextLabel(result, PLACEHOLDER);
  return { ...entry, status: result.status, nextText };
}

function renderSummary(root, snapshot) {
  const { openCount } = snapshot.summary;
  const unit = openCount === 1 ? t("place_singular", "place") : t("place_plural", "places");
  const label = snapshot.horizon.id === "now"
    ? t("open_count_now", "%{unit} open now")
    : t("open_count_horizon", "%{unit} available %{horizon}");
  root.querySelectorAll("[data-open-count]").forEach((node) => { node.textContent = String(openCount); });
  root.querySelectorAll("[data-open-count-label]").forEach((node) => {
    node.textContent = label.replace("%{unit}", unit).replace("%{horizon}", horizonLabel(snapshot.horizon).toLowerCase());
  });
}

function renderControls(root, state) {
  root.querySelectorAll('button[data-filter="type"]').forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.type === (state.type || "none")));
  });
  root.querySelector('button[data-filter="access"][data-access="memberships"]')?.setAttribute("aria-pressed", String(state.includeMemberships));
  root.querySelector('button[data-filter="open-now"]')?.setAttribute("aria-pressed", String(state.sort.kind === "open"));
  root.querySelector('button[data-action="sort-distance"]')?.setAttribute("aria-pressed", String(state.sort.kind === "distance" || state.geo.status === "pending"));
}

export function mountBoard(root = document, { now = () => new Date(), onChange = () => {} } = {}) {
  const tbody = root.querySelector("table.board tbody");
  if (!tbody) return null;
  const rows = [...tbody.querySelectorAll("tr")];
  const spots = readSpots(rows);
  const controller = new AbortController();
  const { signal } = controller;
  let state = initialBoardState();
  let snapshot;
  let horizonMenu;

  function writeURL() {
    const url = new URL(window.location.href);
    if (state.horizon === "now") url.searchParams.delete("when");
    else url.searchParams.set("when", state.horizon);
    url.hash = serializeBoardHash(state);
    history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
    root.querySelectorAll("[data-target-path]").forEach((link) => {
      link.setAttribute("href", link.dataset.targetPath + url.search + url.hash);
    });
  }

  function render(flap) {
    const instant = now();
    const result = evaluateBoard(spots, state, instant);
    snapshot = { ...result, entries: result.entries.map((entry) => presentEntry(entry, result.horizon)) };
    applyHorizonChrome(root, snapshot.horizon, pacificWallClockDate(instant));
    renderControls(root, state);
    horizonMenu?.render({
      buttonLabel: horizonLabel(snapshot.horizon),
      items: getHorizonOptions(pacificWallClockDate(instant)).map((option) => ({
        id: option.id, label: horizonLabel(option), selected: option.id === snapshot.horizon.id,
      })),
    });
    let flapIndex = 0;
    for (const entry of snapshot.entries) {
      const row = rows[entry.index];
      const statusCell = cell(row, "status");
      if (statusCell) setStatus(statusCell, entry.status, entry.type,
        entry.type === "open_water" && snapshot.horizon.id === "now" ? t("status_year_round", "YEAR-ROUND") : "");
      const nextCell = cell(row, "next");
      if (nextCell) nextCell.textContent = entry.nextText;
      row.hidden = entry.hidden;
      row.classList.toggle("is-open", entry.type === "open_water"
        ? snapshot.horizon.id === "now" : OPEN_STATUSES.has(entry.status));
      tbody.appendChild(row);
      if (flap && !entry.hidden) {
        row.classList.remove("flap");
        row.style.setProperty("--flap-index", String(flapIndex++));
        void row.offsetWidth;
        row.classList.add("flap");
      }
    }
    renderSummary(root, snapshot);
    onChange(snapshot);
  }

  function dispatch(action) {
    if (signal.aborted) return;
    const transition = transitionBoard(state, action);
    state = transition.state;
    for (const effect of transition.effects) {
      if (effect.kind === "render") render(effect.flap);
      else if (effect.kind === "controls") renderControls(root, state);
      else if (effect.kind === "write-url") writeURL();
      else if (effect.kind === "capture") {
        capture("filter_applied", effect.trigger === "when" ? { trigger: "when", when: state.horizon } : {
          trigger: effect.trigger, program: state.type || "none", sort: state.sort.kind,
          memberships: state.includeMemberships, when: state.horizon, result_count: snapshot.summary.visibleCount,
        });
      } else if (effect.kind === "geolocate") {
        navigator.geolocation.getCurrentPosition(
          ({ coords }) => dispatch({ type: "geo-success", requestId: effect.requestId,
            coords: { latitude: coords.latitude, longitude: coords.longitude } }),
          () => dispatch({ type: "geo-denied", requestId: effect.requestId }),
        );
      }
    }
  }

  const refresh = () => dispatch({ type: "tick", instant: now() });
  const control = root.querySelector(".horizon-control");
  if (control) horizonMenu = initHorizonMenu(control, {
    refresh,
    onSelect: (horizon, source) => dispatch({ type: "set-horizon", horizon, instant: now(), track: source === "click" }),
  });
  root.querySelectorAll('button[data-filter="type"]').forEach((button) => {
    button.addEventListener("click", () => dispatch({ type: "set-program", program: button.dataset.type }), { signal });
  });
  root.querySelector('button[data-filter="access"][data-access="memberships"]')?.addEventListener("click", () => dispatch({ type: "toggle-memberships" }), { signal });
  root.querySelector('button[data-filter="open-now"]')?.addEventListener("click", () => dispatch({ type: "toggle-open" }), { signal });
  root.querySelector('button[data-action="sort-distance"]')?.addEventListener("click", () => dispatch({ type: "request-distance", available: Boolean(navigator.geolocation) }), { signal });
  root.querySelector("[data-time-banner-reset]")?.addEventListener("click", () => dispatch({ type: "set-horizon", horizon: "now", instant: now(), track: true }), { signal });
  tbody.addEventListener("animationend", (event) => event.target.closest("tr")?.classList.remove("flap"), { signal });
  initRowNavigation(tbody, signal, (row, source) => {
    const entry = snapshot.entries.find((entry) => rows[entry.index] === row);
    if (entry) capture("spot_opened", { slug: entry.slug, spot_type: entry.type, source, status_at_click: entry.status });
  });
  window.addEventListener("hashchange", () => dispatch({ type: "hashchange", hash: window.location.hash }), { signal });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); }, { signal });
  dispatch({ type: "restore", hash: window.location.hash, search: window.location.search, instant: now() });
  const timer = setInterval(refresh, 60_000);
  return {
    refresh,
    dispose() {
      controller.abort();
      clearInterval(timer);
      horizonMenu?.dispose();
      rows.forEach((row) => row.classList.remove("flap"));
    },
  };
}
