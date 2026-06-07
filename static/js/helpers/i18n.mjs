export function t(key, fallback = "") {
  const dict = globalThis.window?.SWIMFRANCISCO_I18N;
  return (dict && typeof dict[key] === "string" && dict[key]) || fallback;
}

export function statusLabel(status) {
  const key = {
    OPEN: "status_open",
    CLOSED: "status_closed",
    ACCESS: "status_access",
    CHECK: "status_check",
    AVAILABLE: "status_available",
    LIMITED: "status_limited",
    OCEAN: "status_ocean",
  }[status];
  return key ? t(key, status) : status;
}

export function programLabel(type) {
  const key = {
    lap_swim: "lap",
    family_swim: "family",
    senior_swim: "senior",
  }[type];
  return key ? t(key, type.toUpperCase()) : type.toUpperCase();
}

export function programLongLabel(type) {
  const key = {
    lap_swim: "lap_swim",
    family_swim: "family_swim",
    senior_swim: "senior_swim",
  }[type];
  return key ? t(key, programLabel(type)) : programLabel(type);
}

export function dayShortLabel(day) {
  const key = {
    monday: "day_monday_short",
    tuesday: "day_tuesday_short",
    wednesday: "day_wednesday_short",
    thursday: "day_thursday_short",
    friday: "day_friday_short",
    saturday: "day_saturday_short",
    sunday: "day_sunday_short",
  }[day];
  return key ? t(key, day.slice(0, 3).toUpperCase()) : String(day || "").toUpperCase();
}

function activeLanguage() {
  return globalThis.window?.SWIMFRANCISCO_LANG || "en";
}

function monthLabel(month) {
  const key = [
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
  ][month - 1];
  const fallback = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"][month - 1];
  return key ? t(key, fallback) : "";
}

export function formatLocalizedISODate(isoDate) {
  if (typeof isoDate !== "string") return "";
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate.trim());
  if (!match) return isoDate;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const lang = activeLanguage();
  if (lang.startsWith("zh")) return `${year}年${month}月${day}日`;
  if (lang.startsWith("fil")) return `${monthLabel(month)} ${day}, ${year}`;
  if (lang.startsWith("fi")) return `${day}.${month}.${year}`;
  if (lang.startsWith("vi") || lang.startsWith("es")) return `${day}/${month}/${year}`;
  const label = monthLabel(month);
  if (lang.startsWith("en")) return `${label} ${day}, ${year}`;
  return `${day} ${label} ${year}`;
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
  return key ? t(key, fallback || reasonCode) : fallback;
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
