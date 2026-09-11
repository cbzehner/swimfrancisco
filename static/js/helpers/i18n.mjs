export function t(key, fallback = "") {
  const dict = globalThis.window?.SWIMFRANCISCO_I18N;
  return (dict && typeof dict[key] === "string" && dict[key]) || fallback;
}

// The four lookups below share one shape: map a domain value to a
// translation key, then fall back to a literal derived from the value —
// `translated` when the key exists but the catalog does not carry it,
// `unknown` when the value itself is off-table.
function labelLookup(keys, translated, unknown = translated) {
  return (value) => {
    const key = keys[value];
    return key ? t(key, translated(value)) : unknown(value);
  };
}

const upperCase = (value) => String(value ?? "").toUpperCase();

export const statusLabel = labelLookup(
  {
    OPEN: "status_open",
    CLOSED: "status_closed",
    ACCESS: "status_access",
    CHECK: "status_check",
    AVAILABLE: "status_available",
    LIMITED: "status_limited",
    OCEAN: "status_ocean",
  },
  (status) => status,
);

export const programLabel = labelLookup(
  {
    lap_swim: "lap",
    family_swim: "family",
    senior_swim: "senior",
  },
  upperCase,
);

export const dayShortLabel = labelLookup(
  {
    monday: "day_monday_short",
    tuesday: "day_tuesday_short",
    wednesday: "day_wednesday_short",
    thursday: "day_thursday_short",
    friday: "day_friday_short",
    saturday: "day_saturday_short",
    sunday: "day_sunday_short",
  },
  (day) => day.slice(0, 3).toUpperCase(),
  upperCase,
);

export const dayFullLabel = labelLookup(
  {
    monday: "day_monday",
    tuesday: "day_tuesday",
    wednesday: "day_wednesday",
    thursday: "day_thursday",
    friday: "day_friday",
    saturday: "day_saturday",
    sunday: "day_sunday",
  },
  upperCase,
);

function activeLanguage() {
  return globalThis.window?.SWIMFRANCISCO_LANG || "en";
}

function sourceStringFallback(value = "") {
  const defaultLanguage = globalThis.window?.SWIMFRANCISCO_DEFAULT_LANG || "en";
  return activeLanguage() === defaultLanguage ? value : "";
}

const MONTH_KEYS = [
  "month_jan",
  "month_feb",
  "month_mar",
  "month_apr",
  "month_may",
  "month_jun",
  "month_jul",
  "month_aug",
  "month_sep",
  "month_oct",
  "month_nov",
  "month_dec",
];
const MONTH_FALLBACKS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
const ISO_DATE_FORMAT = {
  en: "month_d_y",
  fil: "month_d_y",
  es: "dmy_slash",
  vi: "dmy_slash",
  "zh-Hant": "ymd_han",
};

function monthLabel(month) {
  const key = MONTH_KEYS[month - 1];
  const fallback = MONTH_FALLBACKS[month - 1];
  return key ? t(key, fallback) : "";
}

export function formatLocalizedISODate(isoDate) {
  if (typeof isoDate !== "string") return "";
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate.trim());
  if (!match) return isoDate;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const format = ISO_DATE_FORMAT[activeLanguage()] || ISO_DATE_FORMAT.en;
  if (format === "ymd_han") return `${year}年${month}月${day}日`;
  if (format === "dmy_slash") return `${day}/${month}/${year}`;
  const label = monthLabel(month);
  return `${label} ${day}, ${year}`;
}

export function closureReasonLabel(reasonCode, fallback = "") {
  let code = typeof reasonCode === "string" && reasonCode ? reasonCode : "";
  let key = "";
  const labels = globalThis.window?.SWIMFRANCISCO_DYNAMIC_LABELS?.closure_reason || {};
  if (code) {
    const entry = labels.by_code?.[code] || {};
    key = typeof entry.translation_key === "string" ? entry.translation_key : "";
  }
  if (!key && typeof fallback === "string" && fallback) {
    const entry = labels.by_source?.[fallback] || {};
    key = typeof entry.translation_key === "string" ? entry.translation_key : "";
  }
  return key ? t(key, sourceStringFallback(fallback || reasonCode)) : sourceStringFallback(fallback);
}

export function statusNextLabel(result, placeholder = "—") {
  if (!result || result.next === placeholder) return placeholder;
  const args = result.nextArgs || {};
  switch (result.nextKind) {
    case "schedule_starts":
      return `${t("status_schedule_starts", "Schedule starts")} ${formatLocalizedISODate(args.iso)}`;
    case "schedule_ended":
      return `${t("status_schedule_ended", "Schedule ended")} ${formatLocalizedISODate(args.iso)}`;
    case "closed_through":
      return `${t("status_closed_through", "Closed through")} ${formatLocalizedISODate(args.iso)}`;
    case "closed_window":
      return `${t("status_closed_window", "Closed")} ${args.start}\u2013${args.end}`;
    case "not_verified":
      return t("status_not_verified", "SCHEDULE NOT YET VERIFIED");
    case "closes":
      return `${t("status_closes", "Closes")} ${args.time}`;
    case "opens_today":
      return `${t("status_opens", "Opens")} ${args.time}`;
    case "opens_day":
      return `${t("status_opens", "Opens")} ${dayShortLabel(args.day)} ${args.time}`;
    case "until":
      return `${t("status_until", "UNTIL")} ${args.time}`;
    case "official_site":
      return t("status_official_site", "OFFICIAL SITE");
    case "access_today":
      return `${t("status_access_at", "Access")} ${args.time}`;
    case "access_day":
      return `${t("status_access_at", "Access")} ${dayShortLabel(args.day)} ${args.time}`;
    case "closure_reason":
      return closureReasonLabel(args.reasonCode, args.reason);
    default:
      return result.next || placeholder;
  }
}
