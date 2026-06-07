const DROP_IN_TYPE_SET = new Set(["lap_swim", "family_swim", "senior_swim"]);

export function isDropInType(type) {
  return DROP_IN_TYPE_SET.has(type);
}

export const TYPE_TOKENS = Object.freeze({
  lap: "lap_swim",
  beach: "open_water",
  family: "family_swim",
  senior: "senior_swim",
});

export const TYPE_TO_TOKEN = Object.freeze(
  Object.fromEntries(Object.entries(TYPE_TOKENS).map(([token, type]) => [type, token])),
);
