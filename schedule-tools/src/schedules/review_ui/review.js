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
let currentSlug = null;
let currentSha12 = null;
let currentSequential = false;
let envelope = null;
let zoom = "page-width";
let page = 1;
let sourceKind = null;
let sourceUrl = null;
let sourceIdentity = null;
let verifiedSourceIdentity = null;
let sequentialDrafts = {};

const $ = (selector) => document.querySelector(selector);
const pretty = (value) => value.replaceAll("_", " ").replaceAll("-", " ").replace(/\b\w/g, letter => letter.toUpperCase());

async function request(path, options) {
  const response = await fetch(path, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || "Request failed.");
  return value;
}

function itemKey(item) {
  return item.sequential ? `${item.slug}/${item.sha12}` : item.slug;
}

function currentKey() {
  return currentSequential ? `${currentSlug}/${currentSha12}` : currentSlug;
}

function reviewPath(suffix) {
  const base = currentSequential ? `/api/reviews/${currentSlug}/${currentSha12}` : `/api/reviews/${currentSlug}`;
  return suffix ? `${base}/${suffix}` : base;
}

function sourcePath() {
  return currentSequential ? `/source/${currentSlug}/${currentSha12}` : `/source/${currentSlug}`;
}

function siblings() {
  return queue.filter(item => item.slug === currentSlug && item.sequential);
}

async function loadQueue(preferredKey) {
  queue = (await request("/api/reviews")).reviews;
  $("#queue-count").textContent = `${queue.length} pool${queue.length === 1 ? "" : "s"} awaiting review`;
  renderQueue();
  if (!queue.length) {
    $("#workspace").hidden = true;
    $("#empty").hidden = false;
    return;
  }
  const match = queue.find(item => itemKey(item) === preferredKey) || queue.find(item => item.slug === preferredKey) || queue[0];
  await loadReview(match);
}

function renderQueue() {
  const list = $("#queue-list");
  list.replaceChildren(...queue.map(item => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = item.sequential ? `${pretty(item.slug)} · ${item.sha12}` : pretty(item.slug);
    if (sequentialDrafts[itemKey(item)]) button.textContent += " ✓";
    button.setAttribute("aria-current", String(itemKey(item) === currentKey()));
    button.addEventListener("click", () => loadReview(item));
    return button;
  }));
}

async function loadReview(item) {
  const slug = item.slug;
  currentSlug = slug;
  currentSha12 = item.sha12 || null;
  currentSequential = !!item.sequential;
  const data = await request(reviewPath());
  envelope = sequentialDrafts[itemKey(item)] || data.envelope;
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
  $("#save-next").textContent = currentSequential ? "Confirm window →" : "Save & next pool →";
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
  const localUrl = sourcePath();
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
      if (queue.find(item => itemKey(item) === currentKey())?.source_kind === "csv") {
        $("#source-frame").src = `${sourcePath()}#${day}`;
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
    const result = await request(reviewPath("check-source"), { method: "POST" });
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
    const data = await request(reviewPath("refresh"), { method: "POST" });
    delete sequentialDrafts[currentKey()];
    const nextKey = data.candidate?.sequential
      ? `${data.candidate.slug}/${data.candidate.sha12}`
      : data.candidate?.slug;
    await loadQueue(nextKey);
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
    const body = { envelope, attested: $("#attested").checked, source_identity: verifiedSourceIdentity };
    if (currentSequential) {
      await request(reviewPath(), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      sequentialDrafts[currentKey()] = structuredClone(envelope);
      const pending = siblings().filter(item => !sequentialDrafts[itemKey(item)]);
      if (pending.length) {
        $("#save-state").textContent = "Window confirmed";
        await loadReview(pending[0]);
        return;
      }
      const envelopes = Object.fromEntries(
        siblings().map(item => [item.sha12, sequentialDrafts[itemKey(item)]])
      );
      await request(`/api/reviews/${currentSlug}/save-sequential`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ envelopes, attested: true }) });
      for (const item of siblings()) delete sequentialDrafts[itemKey(item)];
    } else {
      await request(reviewPath(), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    }
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
