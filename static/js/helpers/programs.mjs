export const DROP_IN_TYPES = Object.freeze([
  "lap_swim",
  "family_swim",
  "senior_swim",
]);

const DROP_IN_TYPE_SET = new Set(DROP_IN_TYPES);

export function isDropInType(type) {
  return DROP_IN_TYPE_SET.has(type);
}

export const PROGRAM_LABEL = Object.freeze({
  lap_swim: "LAP",
  family_swim: "FAMILY",
  senior_swim: "SENIOR",
});

export const TYPE_TOKENS = Object.freeze({
  lap: "lap_swim",
  beach: "open_water",
  family: "family_swim",
  senior: "senior_swim",
});

export const TYPE_TO_TOKEN = Object.freeze(
  Object.fromEntries(Object.entries(TYPE_TOKENS).map(([token, type]) => [type, token])),
);
