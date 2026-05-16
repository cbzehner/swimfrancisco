const lanes = Array.from(document.querySelectorAll(".fn-lane"));
const title = document.querySelector("[data-lane-title]");
const detail = document.querySelector("[data-lane-detail]");
const link = document.querySelector("[data-lane-link]");

function activate(lane) {
  if (!title || !detail || !link) return;
  for (const item of lanes) {
    item.classList.toggle("is-active", item === lane);
  }
  title.textContent = `${lane.dataset.laneTitle || "The Swim Lane"}.`;
  detail.textContent = lane.dataset.laneDetail || "";
  link.href = lane.dataset.laneLink || "/field-notes/";
  link.textContent = lane.querySelector(".fn-lane-cta")?.textContent || "READ THE DIVE";
}

for (const lane of lanes) {
  lane.addEventListener("mouseenter", () => activate(lane));
  lane.addEventListener("focus", () => activate(lane));
}
