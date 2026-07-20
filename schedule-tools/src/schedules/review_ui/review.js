const days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
const bases = ["swim_schedule", "pool_hours", "facility_hours", "amenity_only", "temporarily_closed", "unknown"];
const types = ["lap_swim", "family_swim", "senior_swim"];
const collections = {
  sessions: { title: "Swim sessions", fields: [["day", "Day", "day"], ["type", "Classification", "type"], ["start", "Start", "time"], ["end", "End", "time"], ["pool", "Pool / zone", "text"], ["evidence", "Source evidence", "text", "wide"], ["notes", "Reviewer note", "text", "wide"]] },
  access_hours: { title: "Access hours", fields: [["day", "Day", "day"], ["start", "Start", "time"], ["end", "End", "time"], ["label", "Label", "text"], ["evidence", "Source evidence", "text", "wide"], ["notes", "Reviewer note", "text", "wide"]] },
  access_exceptions: { title: "Access exceptions", fields: [["date", "Date", "date"], ["start", "Start", "time"], ["end", "End", "time"], ["label", "Label", "text"], ["reason", "Reason", "text", "wide"], ["evidence", "Source evidence", "text", "wide"], ["notes", "Reviewer note", "text", "wide"]] },
  closures: { title: "Closures", fields: [["start", "Start date", "date"], ["end", "End date", "date"], ["start_time", "Start time", "time"], ["end_time", "End time", "time"], ["reason", "Reason", "text", "wide"]] }
};
const rowDefaults = {
  sessions: { day: "monday", type: "lap_swim", start: "09:00", end: "10:00" },
  access_hours: { day: "monday", start: "09:00", end: "10:00", label: "Public access" },
  access_exceptions: { date: "", start: "09:00", end: "10:00", label: "Public access", reason: "Holiday hours" },
  closures: { start: "", end: "", reason: "Facility closed" }
};

let queue = [];
let current = null;
let envelope = null;
let zoom = "page-width";
let page = 1;
let sourceKind = null;
let sourceUrl = null;
let sourceIdentity = null;
let verifiedSourceIdentity = null;

const $ = (selector) => document.querySelector(selector);
const pretty = (value) => value.replaceAll("_", " ").replaceAll("-", " ").replace(/\b\w/g, letter => letter.toUpperCase());

async function request(path, options) {
  const response = await fetch(path, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || "Request failed.");
  return value;
}

async function loadQueue(preferredSlug) {
  queue = (await request("/api/reviews")).reviews;
  $("#queue-count").textContent = `${queue.length} pool${queue.length === 1 ? "" : "s"} awaiting review`;
  renderQueue();
  if (!queue.length) {
    $("#workspace").hidden = true;
    $("#empty").hidden = false;
    return;
  }
  const slug = queue.some(item => item.slug === preferredSlug) ? preferredSlug : queue[0].slug;
  await loadReview(slug);
}

function renderQueue() {
  const list = $("#queue-list");
  list.replaceChildren(...queue.map(item => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = pretty(item.slug);
    button.setAttribute("aria-current", String(item.slug === current));
    button.addEventListener("click", () => loadReview(item.slug));
    return button;
  }));
}

async function loadReview(slug) {
  const data = await request(`/api/reviews/${slug}`);
  current = slug;
  envelope = data.envelope;
  sourceKind = data.candidate.source_kind;
  sourceUrl = envelope.source_pdf_url;
  sourceIdentity = `${slug}:${envelope.pdf_sha256}`;
  verifiedSourceIdentity = null;
  $("#empty").hidden = true;
  $("#workspace").hidden = false;
  $("#pool-name").textContent = pretty(slug);
  const sourceLabels = { pdf: "Captured official PDF", csv: "Captured official Google Sheet", html: "Captured official page" };
  $("#source-label").textContent = `${sourceLabels[sourceKind] || sourceKind.toUpperCase()} · ${data.candidate.fetch_date}`;
  $("#attested").checked = false;
  $("#save-state").textContent = "";
  page = Number(localStorage.getItem(`review-page:${sourceIdentity}`)) || 1;
  zoom = localStorage.getItem(`review-zoom:${sourceIdentity}`) || "page-width";
  $("#pdf-page").value = page;
  $("#pdf-page-control").hidden = sourceKind !== "pdf";
  $("#zoom-in").hidden = sourceKind !== "pdf";
  $("#zoom-out").hidden = sourceKind !== "pdf";
  $("#zoom-label").hidden = sourceKind !== "pdf";
  updateSource();
  renderCursor();
  renderEditor();
  renderQueue();
  setEditorLocked(true);
  await checkSource();
}

function updateSource() {
  const localUrl = `/source/${current}`;
  const suffix = sourceKind === "pdf" ? `#page=${page}&zoom=${zoom}` : "";
  $("#source-frame").src = localUrl + suffix;
  $("#source-new-tab").href = sourceUrl && sourceUrl.startsWith("http") ? sourceUrl : localUrl + suffix;
  $("#zoom-label").textContent = zoom === "page-width" ? "Fit width" : `${zoom}%`;
  localStorage.setItem(`review-page:${sourceIdentity}`, page);
  localStorage.setItem(`review-zoom:${sourceIdentity}`, zoom);
}

function renderCursor() {
  const state = JSON.parse(localStorage.getItem(`review-days:${sourceIdentity}`) || '{"active":"monday","checked":[]}');
  const container = $("#day-cursor");
  container.replaceChildren(...days.map(day => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = day.slice(0, 2).toUpperCase();
    button.title = `${pretty(day)}${state.checked.includes(day) ? " — checked" : ""}`;
    button.classList.toggle("active", state.active === day);
    button.classList.toggle("checked", state.checked.includes(day));
    button.addEventListener("click", () => {
      state.active = day;
      localStorage.setItem(`review-days:${sourceIdentity}`, JSON.stringify(state));
      if (queue.find(item => item.slug === current)?.source_kind === "csv") {
        $("#source-frame").src = `/source/${current}#${day}`;
      }
      renderCursor();
    });
    return button;
  }));
  $("#mark-day").textContent = state.checked.includes(state.active) ? "Mark unchecked" : "Mark checked";
  $("#mark-day").onclick = () => {
    state.checked = state.checked.includes(state.active) ? state.checked.filter(day => day !== state.active) : [...state.checked, state.active];
    localStorage.setItem(`review-days:${sourceIdentity}`, JSON.stringify(state));
    renderCursor();
  };
}

function renderEditor() {
  const payload = envelope.payload;
  $("#effective-start").value = payload.effective_start || "";
  $("#effective-end").value = payload.effective_end || "";
  $("#schedule-basis").replaceChildren(...bases.map(value => new Option(pretty(value), value, false, value === payload.schedule_basis)));
  const root = $("#collections");
  root.replaceChildren(...Object.entries(collections).map(([key, config]) => renderCollection(key, config)));
}

function setEditorLocked(locked) {
  $("#editor").querySelectorAll("input, select, button").forEach(control => control.disabled = locked);
}

function setFreshnessState(message, state) {
  const status = $("#freshness-state");
  status.textContent = message;
  status.className = `freshness-state ${state || ""}`;
}

async function checkSource() {
  const action = $("#freshness-action");
  action.disabled = false;
  action.hidden = true;
  setFreshnessState("Checking official source…", "");
  setEditorLocked(true);
  try {
    const result = await request(`/api/reviews/${current}/check-source`, { method: "POST" });
    if (result.status === "current") {
      verifiedSourceIdentity = result.source_identity;
      setFreshnessState("Current source ✓", "current");
      setEditorLocked(false);
      return;
    }
    verifiedSourceIdentity = null;
    setFreshnessState("Official source changed", "changed");
    action.textContent = "Refresh extraction";
    action.hidden = false;
    action.onclick = refreshSource;
  } catch (error) {
    verifiedSourceIdentity = null;
    setFreshnessState("Source check failed", "error");
    action.textContent = "Retry";
    action.hidden = false;
    action.onclick = checkSource;
    $("#save-state").textContent = error.message;
  }
}

async function refreshSource() {
  const action = $("#freshness-action");
  action.disabled = true;
  setFreshnessState("Refreshing extraction…", "");
  try {
    await request(`/api/reviews/${current}/refresh`, { method: "POST" });
    await loadQueue(current);
  } catch (error) {
    setFreshnessState("Refresh failed", "error");
    $("#save-state").textContent = error.message;
    action.disabled = false;
  }
}

function renderCollection(key, config) {
  envelope.payload[key] ||= [];
  const section = document.createElement("section");
  section.className = "collection";
  const heading = document.createElement("div");
  heading.className = "collection-heading";
  heading.innerHTML = `<h2>${config.title} <span class="num">${envelope.payload[key].length}</span></h2>`;
  const add = document.createElement("button");
  add.className = "small-button";
  add.type = "button";
  add.textContent = "+ Add";
  add.addEventListener("click", () => {
    envelope.payload[key].push({ ...rowDefaults[key] });
    renderEditor();
  });
  heading.append(add);
  section.append(heading);
  if (!envelope.payload[key].length) {
    const empty = document.createElement("p");
    empty.className = "empty-collection";
    empty.textContent = "No rows in the extraction.";
    section.append(empty);
  }
  envelope.payload[key].forEach((row, index) => section.append(renderRow(key, config.fields, row, index)));
  return section;
}

function renderRow(collection, fields, row, index) {
  const element = $("#row-template").content.firstElementChild.cloneNode(true);
  fields.forEach(([key, label, kind, className]) => {
    const wrapper = document.createElement("label");
    wrapper.textContent = label;
    if (className) wrapper.className = className;
    let input;
    if (kind === "day" || kind === "type") {
      input = document.createElement("select");
      const values = kind === "day" ? days : types;
      input.replaceChildren(...values.map(value => new Option(pretty(value), value, false, value === row[key])));
    } else {
      input = document.createElement("input");
      input.type = kind;
      input.value = row[key] || "";
    }
    input.addEventListener("input", () => {
      if (input.value) row[key] = input.value;
      else delete row[key];
      $("#save-state").textContent = "Unsaved changes";
    });
    wrapper.append(input);
    element.append(wrapper);
  });
  const remove = document.createElement("button");
  remove.className = "remove-row";
  remove.type = "button";
  remove.setAttribute("aria-label", `Remove ${collections[collection].title} row ${index + 1}`);
  remove.textContent = "×";
  remove.addEventListener("click", () => {
    envelope.payload[collection].splice(index, 1);
    renderEditor();
  });
  element.append(remove);
  return element;
}

$("#effective-start").addEventListener("input", event => envelope.payload.effective_start = event.target.value);
$("#effective-end").addEventListener("input", event => event.target.value ? envelope.payload.effective_end = event.target.value : delete envelope.payload.effective_end);
$("#schedule-basis").addEventListener("input", event => envelope.payload.schedule_basis = event.target.value);
$("#fullscreen-source").addEventListener("click", () => document.fullscreenElement ? document.exitFullscreen() : $("#source-panel").requestFullscreen());
$("#pdf-page").addEventListener("change", event => { page = Math.max(1, Number(event.target.value) || 1); updateSource(); });
$("#zoom-in").addEventListener("click", () => { zoom = zoom === "page-width" ? 125 : Math.min(300, Number(zoom) + 25); updateSource(); });
$("#zoom-out").addEventListener("click", () => { zoom = zoom === "page-width" ? 75 : Math.max(25, Number(zoom) - 25); updateSource(); });
$("#save-next").addEventListener("click", async () => {
  const button = $("#save-next");
  button.disabled = true;
  $("#save-state").textContent = "Validating…";
  try {
    await request(`/api/reviews/${current}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ envelope, attested: $("#attested").checked, source_identity: verifiedSourceIdentity }) });
    localStorage.removeItem(`review-days:${sourceIdentity}`);
    $("#save-state").textContent = "Saved & projected";
    await loadQueue();
  } catch (error) {
    $("#save-state").textContent = error.message;
    await checkSource();
  } finally {
    button.disabled = false;
  }
});

loadQueue().catch(error => { $("#queue-count").textContent = error.message; });
