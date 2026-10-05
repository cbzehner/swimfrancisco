import { resolveHorizon } from "./board.mjs";
import { pacificWallClockDate } from "./pacific.mjs";
import { TYPE_TOKENS, TYPE_TO_TOKEN } from "./programs.mjs";

const OWNED_TOKENS = new Set(["open", "next-open", "open-now", "distance", "memberships", ...Object.keys(TYPE_TOKENS)]);
// Match the board's program-control order when a link supplies several types.
const PROGRAM_TYPES = ["lap_swim", "family_swim", "senior_swim", "open_water"];

export function parseBoardHash(hash) {
  const tokens = new Set(hash.replace(/^#/, "").split("+").filter(Boolean));
  return {
    type: PROGRAM_TYPES.find((type) => tokens.has(TYPE_TO_TOKEN[type])) || null,
    includeMemberships: tokens.has("memberships"),
    open: ["open", "next-open", "open-now"].some((token) => tokens.has(token)),
    distance: tokens.has("distance"),
    foreignTokens: [...tokens].filter((token) => !OWNED_TOKENS.has(token)),
  };
}

export function serializeBoardHash(state) {
  const tokens = new Set(state.foreignTokens);
  if (state.sort.kind === "open") tokens.add("open");
  if (state.sort.kind === "distance") tokens.add("distance");
  if (state.includeMemberships) tokens.add("memberships");
  if (state.type) tokens.add(TYPE_TO_TOKEN[state.type]);
  return tokens.size ? `#${[...tokens].sort().join("+")}` : "";
}

export function initialBoardState() {
  return {
    horizon: "now", type: null, includeMemberships: false,
    sort: { kind: "default" }, geo: { status: "idle" },
    requestId: 0, foreignTokens: [],
  };
}

function render(state, { flap = true, trigger } = {}) {
  return {
    state,
    effects: [
      { kind: "render", flap }, { kind: "write-url" },
      ...(trigger ? [{ kind: "capture", trigger }] : []),
    ],
  };
}

// User intent and asynchronous replies have one owner. Effects are interpreted
// by the browser adapter; this function never reads the DOM, clock, or URL.
export function transitionBoard(state, action) {
  switch (action.type) {
    case "restore":
    case "hashchange": {
      const parsed = parseBoardHash(action.hash);
      const keepDistance = action.type === "hashchange" && parsed.distance && state.sort.kind === "distance";
      return render({
        ...state,
        horizon: action.type === "restore"
          ? resolveHorizon(new URLSearchParams(action.search).get("when"), pacificWallClockDate(action.instant)).id
          : state.horizon,
        type: parsed.type, includeMemberships: parsed.includeMemberships, foreignTokens: parsed.foreignTokens,
        sort: parsed.open ? { kind: "open" } : keepDistance ? state.sort : { kind: "default" },
        geo: { status: "idle" },
      });
    }
    case "set-program":
      return render({ ...state, type: action.program === "none" ? null : action.program }, { trigger: "program" });
    case "toggle-memberships":
      return render({ ...state, includeMemberships: !state.includeMemberships }, { trigger: "memberships" });
    case "toggle-open":
      return render({ ...state, geo: { status: "idle" }, sort: { kind: state.sort.kind === "open" ? "default" : "open" } }, { trigger: "open_sort" });
    case "set-horizon":
      return render({ ...state, horizon: resolveHorizon(action.horizon, pacificWallClockDate(action.instant)).id },
        { trigger: action.track ? "when" : undefined });
    case "tick":
      return render({ ...state, horizon: resolveHorizon(state.horizon, pacificWallClockDate(action.instant)).id }, { flap: false });
    case "request-distance": {
      if (state.geo.status === "pending") break;
      if (state.sort.kind === "distance") {
        return render({ ...state, sort: { kind: "default" }, geo: { status: "idle" } }, { trigger: "distance_sort" });
      }
      if (!action.available) break;
      const requestId = state.requestId + 1;
      return {
        state: { ...state, requestId, geo: { status: "pending", requestId } },
        effects: [{ kind: "controls" }, { kind: "geolocate", requestId }],
      };
    }
    case "geo-success":
    case "geo-denied":
      if (state.geo.status !== "pending" || state.geo.requestId !== action.requestId) break;
      if (action.type === "geo-denied") {
        return { state: { ...state, geo: { status: "idle" } }, effects: [{ kind: "controls" }] };
      }
      return render({ ...state, geo: { status: "idle" }, sort: { kind: "distance", coords: action.coords } }, { trigger: "distance_sort" });
  }
  return { state, effects: [] };
}
