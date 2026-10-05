// Literal schedules shared by pure-model and browser wiring tests.
export const programSpots = [
  { slug: "mixed-programs", schedules: [{
    effective_start: "2026-09-01", effective_end: "2026-10-31",
    sessions: [
      { day: "thursday", type: "lap_swim", start: "11:00", end: "14:00" },
      { day: "thursday", type: "family_swim", start: "15:00", end: "16:00" },
      { day: "thursday", type: "senior_swim", start: "09:00", end: "10:00" },
    ],
  }] },
  { slug: "lap-only", schedules: [{
    effective_start: "2026-09-01", effective_end: "2026-10-31",
    sessions: [{ day: "thursday", type: "lap_swim", start: "11:00", end: "14:00" }],
  }] },
  { slug: "members-family", access: "membership", schedules: [{
    effective_start: "2026-09-01", effective_end: "2026-10-31",
    sessions: [{ day: "thursday", type: "family_swim", start: "11:00", end: "13:00" }],
  }] },
];

export function catalog(spots) {
  return spots.map(({ slug, name = slug, type = "pool", access = "public", schedules = [], ...rest }) => ({
    slug, name, label: name, type, accessMode: access, schedule: { schedules }, ...rest,
  }));
}
