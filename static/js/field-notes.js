const nodes = Array.from(document.querySelectorAll(".fn-system-node"));
const detail = document.querySelector("[data-system-detail]");
const link = document.querySelector("[data-system-link]");

function activate(node) {
  if (!detail || !link) return;
  for (const item of nodes) {
    item.classList.toggle("is-active", item === node);
  }
  detail.textContent = node.dataset.systemDetail || "";
  link.href = node.dataset.systemLink || "/field-notes/";
  link.textContent = `READ ${node.dataset.systemTitle || "FIELD NOTE"}`;
}

for (const node of nodes) {
  node.addEventListener("click", () => activate(node));
  node.addEventListener("focus", () => activate(node));
}
