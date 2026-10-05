import { mountBoard } from "./board.js";
import { mountConditions } from "./conditions.js";
import { mountDetail } from "./detail.js";
import { mountMap } from "./map.js";
import { mountChrome } from "./chrome.js";

// Page composition is explicit. Board and conditions updates pass values to
// the map directly, with no globals, custom events, or DOM read-back.
export function mountSite(root = document, { now = () => new Date() } = {}) {
  let snapshot;
  let conditions = {};
  let map;
  const board = mountBoard(root, { now, onChange(next) {
    snapshot = next;
    map?.update(snapshot, conditions, next.instant);
  } });
  map = mountMap(root, { snapshot, conditions, instant: snapshot?.instant || now() });
  const feed = root.querySelector(".bulletin-strip[data-bay-slugs], section.conditions[data-slug], table.board")
    ? mountConditions(root, { now, onChange(next, instant) {
      conditions = next;
      map?.update(snapshot, conditions, instant);
    } }) : null;
  const detail = root.querySelector(".detail-root, section.conditions") ? mountDetail(root, { now }) : null;
  const chrome = mountChrome(root);
  return {
    refresh() { for (const component of [board, feed, detail]) component?.refresh(); },
    dispose() { for (const component of [board, feed, detail, map, chrome]) component?.dispose(); },
  };
}
