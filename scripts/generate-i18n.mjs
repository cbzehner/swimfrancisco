import { mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { parse, stringify } from "smol-toml";
import { splitFrontMatter } from "./lib/spot-frontmatter.mjs";

const ROOT = process.cwd();
const CONFIG_PATH = path.join(ROOT, "config.toml");
const SOURCE_DIR = path.join(ROOT, "i18n");
const UI_DIR = path.join(SOURCE_DIR, "ui");
const SPOTS_DIR = path.join(SOURCE_DIR, "spots");
const SECTIONS_DIR = path.join(SOURCE_DIR, "sections");
const SOURCE_LOCALES_PATH = path.join(SOURCE_DIR, "locales.toml");
const SOURCE_DYNAMIC_LABELS_PATH = path.join(SOURCE_DIR, "dynamic-labels.toml");
const DATA_I18N_DIR = path.join(ROOT, "data", "i18n");
const DATA_DYNAMIC_LABELS_JSON_PATH = path.join(DATA_I18N_DIR, "dynamic-labels.json");
const CONTENT_DIR = path.join(ROOT, "content");
const CONTENT_SPOTS_DIR = path.join(ROOT, "content", "spots");
const TRANSLATION_CALLSITE_DIRS = [
  path.join(ROOT, "templates"),
  path.join(ROOT, "static", "js"),
];
const SECTION_TARGETS = {
  home: "_index",
  map: "map/_index",
  spots: "spots/_index",
};
const REQUIRED_DYNAMIC_LABEL_KINDS = ["access_window", "closure_reason", "spot_label"];
const SPOT_TRANSLATABLE_EXTRA_FIELDS = [
  "access_notes",
  "access_summary",
  "clubs",
  "common_distances",
  "description_short",
  "hazards",
  "pricing",
];

function usage() {
  console.error("Usage: node scripts/generate-i18n.mjs <generate|check>");
}

async function readToml(file) {
  return parse(await readFile(file, "utf8"));
}

function tomlText(object) {
  return `${stringify(object).trim()}\n`;
}

function parseFrontMatter(text, file) {
  const { front, body } = splitFrontMatter(text, file, {
    missingMessage: `${file} is missing TOML front matter`,
  });
  return { front, body: body.trim() };
}

async function writeIfChanged(file, text, { dryRun = false, changed = [], written = new Set() } = {}) {
  written.add(path.relative(ROOT, file));
  const prior = existsSync(file) ? await readFile(file, "utf8") : null;
  if (prior === text) return false;
  changed.push(path.relative(ROOT, file));
  if (!dryRun) {
    await mkdir(path.dirname(file), { recursive: true });
    await writeFile(file, text);
  }
  return true;
}

function sourceLocaleCodes(localeData) {
  return localeData.locales.map((locale) => locale.code);
}

function nonDefaultLocaleCodes(localeData) {
  return localeData.locales.filter((locale) => !locale.is_default).map((locale) => locale.code);
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function tomlCatalogCodes(dir) {
  if (!existsSync(dir)) return [];
  return (await readdir(dir))
    .filter((file) => file.endsWith(".toml"))
    .map((file) => file.replace(/\.toml$/, ""))
    .sort();
}

async function validateCatalogFiles({ allCodes }) {
  const catalogSets = [
    { dir: UI_DIR, label: "i18n/ui", expected: allCodes },
    { dir: SPOTS_DIR, label: "i18n/spots", expected: allCodes },
    { dir: SECTIONS_DIR, label: "i18n/sections", expected: allCodes },
  ];

  for (const { dir, label, expected } of catalogSets) {
    const actual = await tomlCatalogCodes(dir);
    const missing = expected.filter((code) => !actual.includes(code));
    const extra = actual.filter((code) => !expected.includes(code));
    if (missing.length || extra.length) {
      throw new Error(
        `${label} locale file mismatch; missing: ${missing.join(", ") || "none"}; extra: ${extra.join(", ") || "none"}`,
      );
    }
  }
}

function mergePricingRows(currentPricing = [], catalogPricing = []) {
  return catalogPricing.map((item, index) => ({
    ...(currentPricing[index] || {}),
    ...item,
  }));
}

function isPresentCatalogValue(value) {
  if (value === undefined || value === null) return false;
  if (typeof value === "string") return value.trim() !== "";
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.keys(value).length > 0;
  return true;
}

async function loadDynamicLabels() {
  if (!existsSync(SOURCE_DYNAMIC_LABELS_PATH)) {
    throw new Error("i18n/dynamic-labels.toml is missing");
  }
  return readToml(SOURCE_DYNAMIC_LABELS_PATH);
}

function dynamicLabelRecords(dynamicLabels) {
  const records = [];
  for (const [kind, items] of Object.entries(dynamicLabels)) {
    if (!Array.isArray(items)) continue;
    for (const item of items) {
      records.push({ kind, ...item });
    }
  }
  return records;
}

function dynamicLabelMap(dynamicLabels) {
  const byKind = {};
  for (const record of dynamicLabelRecords(dynamicLabels)) {
    byKind[record.kind] ||= { by_code: {}, by_source: {} };
    byKind[record.kind].by_code[record.code] = {
      translation_key: record.translation_key,
      sources: [...(record.sources || [])],
    };
    for (const source of record.sources || []) {
      byKind[record.kind].by_source[source] = {
        code: record.code,
        translation_key: record.translation_key,
      };
    }
  }
  return byKind;
}

function dynamicLabelData(dynamicLabels) {
  return dynamicLabelMap(dynamicLabels);
}

function isLocalizedSpotFile(file, localeCodes) {
  return localeCodes.some((code) => file.endsWith(`.${code}.md`));
}

async function canonicalSpotExtras(localeCodes) {
  const files = await readdir(CONTENT_SPOTS_DIR);
  const extras = [];
  for (const file of files) {
    if (!file.endsWith(".md") || file.startsWith("_index.") || isLocalizedSpotFile(file, localeCodes)) continue;
    const { front } = parseFrontMatter(await readFile(path.join(CONTENT_SPOTS_DIR, file), "utf8"), file);
    extras.push({ file, extra: front.extra || {} });
  }
  return extras;
}

async function canonicalSpotSlugs(localeCodes) {
  return (await canonicalSpotExtras(localeCodes))
    .map(({ file }) => file.replace(/\.md$/, ""))
    .sort();
}

function placeholders(value) {
  if (typeof value !== "string") return [];
  return Array.from(value.matchAll(/%\{([A-Za-z0-9_]+)\}/g), (match) => match[1]).sort();
}

function unique(values) {
  return Array.from(new Set(values));
}

async function filesIn(dir, extensions) {
  if (!existsSync(dir)) return [];
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...await filesIn(fullPath, extensions));
    } else if (extensions.some((extension) => entry.name.endsWith(extension))) {
      files.push(fullPath);
    }
  }
  return files;
}

async function staticTranslationCallsiteKeys() {
  const files = (await Promise.all(
    TRANSLATION_CALLSITE_DIRS.map((dir) => filesIn(dir, [".html", ".js", ".mjs"])),
  )).flat();
  const keys = new Map();
  const patterns = [
    /\btrans\(\s*key\s*=\s*["']([A-Za-z0-9_]+)["']/g,
    /(?<![A-Za-z0-9_$])t\(\s*["']([A-Za-z0-9_]+)["']/g,
  ];

  for (const file of files) {
    const text = await readFile(file, "utf8");
    for (const pattern of patterns) {
      for (const match of text.matchAll(pattern)) {
        const key = match[1];
        keys.set(key, keys.get(key) || path.relative(ROOT, file));
      }
    }
  }
  return keys;
}

async function runtimeTranslationKeys(defaultUi, dynamicLabels) {
  const files = await filesIn(path.join(ROOT, "static", "js"), [".js", ".mjs"]);
  const defaultKeys = new Set(Object.keys(defaultUi || {}));
  const runtimeKeys = new Set();
  const stringPattern = /["']([a-z][a-z0-9_]+)["']/g;

  for (const file of files) {
    const text = await readFile(file, "utf8");
    for (const match of text.matchAll(stringPattern)) {
      if (defaultKeys.has(match[1])) runtimeKeys.add(match[1]);
    }
  }

  for (const record of dynamicLabelRecords(dynamicLabels)) {
    if (defaultKeys.has(record.translation_key)) runtimeKeys.add(record.translation_key);
  }

  return Array.from(runtimeKeys).sort();
}

function dynamicLabelRequirements(extrasByFile) {
  const requirements = [];
  for (const { file, extra } of extrasByFile) {
    if (extra.subtype) requirements.push({ kind: "spot_label", source: String(extra.subtype), file });
    if (extra.access_label) requirements.push({ kind: "spot_label", source: String(extra.access_label), file });
    if (extra.setpoint_label && /^[a-z][a-z +/.-]*$/i.test(String(extra.setpoint_label))) {
      requirements.push({ kind: "spot_label", source: String(extra.setpoint_label), file });
    }
    for (const closure of extra.closures || []) {
      if (closure.reason) {
        requirements.push({
          kind: "closure_reason",
          source: String(closure.reason),
          code: closure.reason_code ? String(closure.reason_code) : "",
          file,
        });
      }
    }
    for (const exception of extra.access_exceptions || []) {
      if (exception.label) requirements.push({ kind: "access_window", source: String(exception.label), file });
      if (exception.reason) {
        requirements.push({
          kind: "closure_reason",
          source: String(exception.reason),
          code: exception.reason_code ? String(exception.reason_code) : "",
          file,
        });
      }
    }
  }
  return requirements;
}

async function validateLocaleRegistryConsumers(codes) {
  const requiredConsumers = [
    path.join(ROOT, "templates", "macros", "chrome.html"),
    path.join(ROOT, "templates", "macros", "seo.html"),
    path.join(ROOT, "templates", "sitemap.xml"),
  ];
  for (const file of requiredConsumers) {
    const text = await readFile(file, "utf8");
    if (!text.includes('load_data(path="i18n/locales.toml")')) {
      throw new Error(`${path.relative(ROOT, file)} must load i18n/locales.toml for locale metadata`);
    }
  }

  const localeAlternation = codes.filter((code) => code !== "en").map((code) => code.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
  if (!localeAlternation) return;
  const hardcodedLocalePattern = new RegExp(`(lang|hreflang|og_locale|locale|code)\\s*(==|=|:)\\s*["'](?:${localeAlternation})["']`);
  for (const file of requiredConsumers) {
    const text = await readFile(file, "utf8");
    if (hardcodedLocalePattern.test(text)) {
      throw new Error(`${path.relative(ROOT, file)} appears to hardcode a locale instead of using i18n/locales.toml`);
    }
  }
}

async function loadSources() {
  const locales = await readToml(SOURCE_LOCALES_PATH);
  const ui = {};
  for (const code of sourceLocaleCodes(locales)) {
    ui[code] = await readToml(path.join(UI_DIR, `${code}.toml`));
  }
  return { locales, ui };
}

function validateLocaleCodes(locales) {
  const defaults = locales.locales.filter((locale) => locale.is_default);
  if (defaults.length !== 1) throw new Error("i18n/locales.toml must define exactly one default locale");

  const codes = sourceLocaleCodes(locales);
  const duplicateCodes = codes.filter((code, index) => codes.indexOf(code) !== index);
  if (duplicateCodes.length > 0) {
    throw new Error(`i18n/locales.toml contains duplicate locale code(s): ${duplicateCodes.join(", ")}`);
  }

  return { defaultLocale: defaults[0], codes };
}

async function validateUiCatalogs({ codes, defaultLocale, ui }) {
  await validateCatalogFiles({ allCodes: codes });

  const defaultKeys = Object.keys(ui[defaultLocale.code] || {}).sort();
  for (const code of codes) {
    const keys = Object.keys(ui[code] || {}).sort();
    const missing = defaultKeys.filter((key) => !keys.includes(key));
    const extra = keys.filter((key) => !defaultKeys.includes(key));
    if (missing.length || extra.length) {
      throw new Error(
        `i18n/ui/${code}.toml key mismatch; missing: ${missing.join(", ") || "none"}; extra: ${extra.join(", ") || "none"}`,
      );
    }
    for (const key of defaultKeys) {
      const defaultPlaceholders = placeholders(ui[defaultLocale.code][key]);
      const localePlaceholders = placeholders(ui[code][key]);
      if (defaultPlaceholders.join(",") !== localePlaceholders.join(",")) {
        throw new Error(
          `i18n/ui/${code}.toml placeholder mismatch for ${key}; expected: ${defaultPlaceholders.join(",") || "none"}; actual: ${localePlaceholders.join(",") || "none"}`,
        );
      }
    }
  }

  const callsiteKeys = await staticTranslationCallsiteKeys();
  const missingCallsiteKeys = Array.from(callsiteKeys.keys())
    .filter((key) => !defaultKeys.includes(key))
    .sort();
  if (missingCallsiteKeys.length > 0) {
    const details = missingCallsiteKeys
      .map((key) => `${key} in ${callsiteKeys.get(key)}`)
      .join("; ");
    throw new Error(`static translation callsite(s) reference missing UI key(s): ${details}`);
  }
}

async function validateDynamicLabels({ codes, ui, dynamicLabels }) {
  const records = dynamicLabelRecords(dynamicLabels);
  const dynamicLabelKinds = unique(records.map((record) => record.kind)).sort();
  const missingDynamicKinds = REQUIRED_DYNAMIC_LABEL_KINDS.filter((kind) => !dynamicLabelKinds.includes(kind));
  if (records.length === 0 || missingDynamicKinds.length > 0) {
    throw new Error(
      `i18n/dynamic-labels.toml must define ${REQUIRED_DYNAMIC_LABEL_KINDS.join(", ")} label kinds; missing: ${missingDynamicKinds.join(", ") || "none"}`,
    );
  }
  const codePattern = /^[a-z][a-z0-9_]*$/;
  const seenSources = new Set();
  const seenCodes = new Set();
  for (const record of records) {
    if (!record.kind || !record.code || !record.translation_key || !Array.isArray(record.sources) || record.sources.length === 0) {
      throw new Error("i18n/dynamic-labels.toml records must include kind, code, translation_key, and a sources list");
    }
    if (!codePattern.test(record.code)) {
      throw new Error(`i18n/dynamic-labels.toml has invalid code for ${record.kind}:${record.code}`);
    }
    const codeIdentity = `${record.kind}:${record.code}`;
    if (seenCodes.has(codeIdentity)) throw new Error(`i18n/dynamic-labels.toml duplicates code: ${codeIdentity}`);
    seenCodes.add(codeIdentity);
    for (const source of record.sources) {
      if (typeof source !== "string" || source === "") {
        throw new Error(`i18n/dynamic-labels.toml has invalid source for ${codeIdentity}`);
      }
      const sourceIdentity = `${record.kind}:${source}`;
      if (seenSources.has(sourceIdentity)) {
        throw new Error(`i18n/dynamic-labels.toml duplicates source: ${sourceIdentity}`);
      }
      seenSources.add(sourceIdentity);
    }
    for (const code of codes) {
      if (!ui[code][record.translation_key]) {
        throw new Error(`i18n/dynamic-labels.toml references missing ${code} translation key: ${record.translation_key}`);
      }
    }
  }

  const dynamicLabelsByKind = dynamicLabelMap(dynamicLabels);
  const extras = await canonicalSpotExtras(codes);
  const requirements = dynamicLabelRequirements(extras);
  const missingDynamicLabels = requirements.filter(
    (requirement) => !dynamicLabelsByKind[requirement.kind]?.by_source?.[requirement.source],
  );
  if (missingDynamicLabels.length > 0) {
    const details = missingDynamicLabels
      .map((item) => `${item.kind}:${JSON.stringify(item.source)} in ${item.file}`)
      .join("; ");
    throw new Error(`i18n/dynamic-labels.toml is missing canonical display label(s): ${details}`);
  }
  const missingDynamicCodes = requirements.filter(
    (requirement) => requirement.code && !dynamicLabelsByKind[requirement.kind]?.by_code?.[requirement.code],
  );
  if (missingDynamicCodes.length > 0) {
    const details = missingDynamicCodes
      .map((item) => `${item.kind}:${item.code} for ${JSON.stringify(item.source)} in ${item.file}`)
      .join("; ");
    throw new Error(`i18n/dynamic-labels.toml is missing canonical display code(s): ${details}`);
  }
  const mismatchedDynamicCodes = requirements.filter((requirement) => {
    if (!requirement.code) return false;
    const mapped = dynamicLabelsByKind[requirement.kind]?.by_source?.[requirement.source];
    return Boolean(mapped) && mapped.code !== requirement.code;
  });
  if (mismatchedDynamicCodes.length > 0) {
    const details = mismatchedDynamicCodes
      .map((item) => {
        const mapped = dynamicLabelsByKind[item.kind].by_source[item.source].code;
        return `${item.kind}:${JSON.stringify(item.source)} maps to ${mapped}, not ${item.code} in ${item.file}`;
      })
      .join("; ");
    throw new Error(`spot reason_code must match by_source[source].code: ${details}`);
  }
}

async function validateSectionCatalogs({ codes }) {
  const requiredSections = Object.keys(SECTION_TARGETS).sort();
  for (const code of codes) {
    const catalogPath = path.join(SECTIONS_DIR, `${code}.toml`);
    if (!existsSync(catalogPath)) throw new Error(`i18n/sections/${code}.toml is missing`);
    const catalog = await readToml(catalogPath);
    const sections = Object.keys(catalog.sections || {}).sort();
    const missing = requiredSections.filter((section) => !sections.includes(section));
    const extra = sections.filter((section) => !requiredSections.includes(section));
    if (missing.length || extra.length) {
      throw new Error(
        `i18n/sections/${code}.toml section mismatch; missing: ${missing.join(", ") || "none"}; extra: ${extra.join(", ") || "none"}`,
      );
    }
  }
}

async function validateSpotCatalogs({ codes, defaultLocale }) {
  const expectedSpotSlugs = await canonicalSpotSlugs(codes);
  const defaultSpotCatalog = await readToml(path.join(SPOTS_DIR, `${defaultLocale.code}.toml`));
  for (const code of codes) {
    const catalog = await readToml(path.join(SPOTS_DIR, `${code}.toml`));
    const slugs = unique(Object.keys(catalog.spots || {})).sort();
    const missing = expectedSpotSlugs.filter((slug) => !slugs.includes(slug));
    const extra = slugs.filter((slug) => !expectedSpotSlugs.includes(slug));
    if (missing.length || extra.length) {
      throw new Error(
        `i18n/spots/${code}.toml slug mismatch; missing: ${missing.join(", ") || "none"}; extra: ${extra.join(", ") || "none"}`,
      );
    }
    if (code === defaultLocale.code) continue;
    const missingFields = [];
    for (const slug of expectedSpotSlugs) {
      const defaultSpot = defaultSpotCatalog.spots?.[slug] || {};
      const translatedSpot = catalog.spots?.[slug] || {};
      for (const [field, value] of Object.entries(defaultSpot)) {
        if (isPresentCatalogValue(value) && !isPresentCatalogValue(translatedSpot[field])) {
          missingFields.push(`${slug}.${field}`);
        }
      }
    }
    if (missingFields.length > 0) {
      throw new Error(`i18n/spots/${code}.toml missing translated spot field(s): ${missingFields.join(", ")}`);
    }
  }
}

async function validateSources(sources, dynamicLabels) {
  const { locales, ui } = sources;
  const { defaultLocale, codes } = validateLocaleCodes(locales);
  await validateLocaleRegistryConsumers(codes);
  await validateUiCatalogs({ codes, defaultLocale, ui });
  await validateDynamicLabels({ codes, ui, dynamicLabels });
  await validateSectionCatalogs({ codes });
  await validateSpotCatalogs({ codes, defaultLocale });
}

async function generatedSectionArtifactsOnDisk() {
  const artifacts = [];
  for (const target of Object.values(SECTION_TARGETS)) {
    const dir = path.dirname(path.join(CONTENT_DIR, target));
    const stem = path.basename(target);
    if (!existsSync(dir)) continue;
    const pattern = new RegExp(`^${escapeRegExp(stem)}\\..+\\.md$`);
    for (const file of await readdir(dir)) {
      if (pattern.test(file)) artifacts.push(path.relative(ROOT, path.join(dir, file)));
    }
  }
  return artifacts;
}

async function generatedSpotArtifactsOnDisk(localeCodes) {
  const artifacts = [];
  if (!existsSync(CONTENT_SPOTS_DIR)) return artifacts;
  for (const file of await readdir(CONTENT_SPOTS_DIR)) {
    if (!file.endsWith(".md") || file.startsWith("_index.")) continue;
    if (!isLocalizedSpotFile(file, localeCodes)) continue;
    artifacts.push(path.relative(ROOT, path.join(CONTENT_SPOTS_DIR, file)));
  }
  return artifacts;
}

async function generatedRuntimeArtifactsOnDisk() {
  const artifacts = [];
  if (!existsSync(DATA_I18N_DIR)) return artifacts;
  for (const file of await readdir(DATA_I18N_DIR)) {
    if (file.endsWith(".json") || file.endsWith(".toml")) {
      artifacts.push(path.relative(ROOT, path.join(DATA_I18N_DIR, file)));
    }
  }
  return artifacts;
}

async function removeStaleGeneratedArtifacts({ dryRun = false, changed = [], written = new Set(), sources } = {}) {
  // Must run after the writers so `written` is the set of files this pass
  // produced. Do not reconstruct that set from a parallel path model.
  const localeCodes = sourceLocaleCodes(sources.locales);
  const actual = [
    ...(await generatedRuntimeArtifactsOnDisk()),
    ...(await generatedSectionArtifactsOnDisk()),
    ...(await generatedSpotArtifactsOnDisk(localeCodes)),
  ];
  const stale = unique(actual.filter((file) => !written.has(file))).sort();

  for (const file of stale) {
    changed.push(file);
    if (!dryRun) await rm(path.join(ROOT, file), { force: true });
  }
}

async function generateConfig({ dryRun = false, changed = [], written = new Set(), sources } = {}) {
  const current = await readToml(CONFIG_PATH);
  const { locales, ui } = sources;
  const defaultLocale = locales.locales.find((locale) => locale.is_default);
  if (!defaultLocale) throw new Error("i18n/locales.toml must define one default locale");

  const next = {};
  for (const [key, value] of Object.entries(current)) {
    if (key !== "translations" && key !== "languages") next[key] = value;
  }
  next.default_language = defaultLocale.code;
  next.title = defaultLocale.title;
  next.description = defaultLocale.description;
  next.translations = ui[defaultLocale.code];
  next.languages = {};
  for (const locale of locales.locales) {
    if (locale.is_default) continue;
    next.languages[locale.code] = {
      title: locale.title,
      description: locale.description,
      translations: ui[locale.code],
    };
  }

  return writeIfChanged(CONFIG_PATH, tomlText(next), { dryRun, changed, written });
}

async function generateRuntimeData({ dryRun = false, changed = [], written = new Set(), sources, dynamicLabels } = {}) {
  const { locales, ui } = sources;
  const dynamicLabelPayload = dynamicLabelData(dynamicLabels);
  const defaultLocale = locales.locales.find((locale) => locale.is_default);
  const runtimeKeys = await runtimeTranslationKeys(ui[defaultLocale.code], dynamicLabels);
  if (!dryRun) await mkdir(DATA_I18N_DIR, { recursive: true });
  for (const code of sourceLocaleCodes(locales)) {
    const runtimeUi = Object.fromEntries(runtimeKeys.map((key) => [key, ui[code][key]]));
    const file = path.join(DATA_I18N_DIR, `${code}.json`);
    await writeIfChanged(file, `${JSON.stringify(runtimeUi, null, 2)}\n`, { dryRun, changed, written });
  }
  await writeIfChanged(
    DATA_DYNAMIC_LABELS_JSON_PATH,
    `${JSON.stringify(dynamicLabelPayload, null, 2)}\n`,
    { dryRun, changed, written },
  );
}

function spotMarkdown(slug, spot) {
  const { body = "", title, slug: localizedSlug = slug, ...extra } = spot;
  const front = {
    title,
    slug: localizedSlug,
    extra: {
      localized_from: slug,
      ...extra,
    },
  };
  return `+++\n${tomlText(front)}+++\n\n${body ? `${body.trim()}\n` : ""}`;
}

function canonicalSpotMarkdown(currentText, slug, spot) {
  const { front } = parseFrontMatter(currentText, slug);
  const { body = "", title, slug: localizedSlug = slug, ...extra } = spot;
  const nextExtra = { ...(front.extra || {}) };
  for (const field of SPOT_TRANSLATABLE_EXTRA_FIELDS) delete nextExtra[field];
  Object.assign(nextExtra, extra);
  if (extra.pricing) nextExtra.pricing = mergePricingRows(front.extra?.pricing, extra.pricing);
  delete nextExtra.localized_from;
  const nextFront = {
    ...front,
    title,
    slug: localizedSlug,
    extra: nextExtra,
  };
  return `+++\n${tomlText(nextFront)}+++\n\n${body ? `${body.trim()}\n` : ""}`;
}

function sectionMarkdown(section) {
  return `+++\n${tomlText(section)}+++\n`;
}

async function generateSectionPages({ dryRun = false, changed = [], written = new Set(), sources } = {}) {
  const { locales } = sources;
  const defaultLocale = locales.locales.find((locale) => locale.is_default);

  for (const code of sourceLocaleCodes(locales)) {
    const catalog = await readToml(path.join(SECTIONS_DIR, `${code}.toml`));
    for (const [sectionKey, target] of Object.entries(SECTION_TARGETS)) {
      const section = catalog.sections?.[sectionKey];
      if (!section) throw new Error(`i18n/sections/${code}.toml is missing ${sectionKey}`);
      const suffix = code === defaultLocale.code ? "" : `.${code}`;
      const file = path.join(CONTENT_DIR, `${target}${suffix}.md`);
      await writeIfChanged(file, sectionMarkdown(section), { dryRun, changed, written });
    }
  }
}

async function generateSpotPages({ dryRun = false, changed = [], written = new Set(), sources } = {}) {
  const { locales } = sources;
  const defaultLocale = locales.locales.find((locale) => locale.is_default);

  for (const code of sourceLocaleCodes(locales)) {
    const catalogPath = path.join(SPOTS_DIR, `${code}.toml`);
    if (!existsSync(catalogPath)) continue;
    const catalog = await readToml(catalogPath);
    for (const [slug, spot] of Object.entries(catalog.spots || {})) {
      if (code === defaultLocale.code) {
        const file = path.join(CONTENT_SPOTS_DIR, `${slug}.md`);
        const currentText = existsSync(file) ? await readFile(file, "utf8") : "";
        await writeIfChanged(file, canonicalSpotMarkdown(currentText, slug, spot), { dryRun, changed, written });
      } else {
        const file = path.join(CONTENT_SPOTS_DIR, `${slug}.${code}.md`);
        await writeIfChanged(file, spotMarkdown(slug, spot), { dryRun, changed, written });
      }
    }
  }
}

async function generateAll({ dryRun = false } = {}) {
  const sources = await loadSources();
  const dynamicLabels = await loadDynamicLabels();
  await validateSources(sources, dynamicLabels);
  const changed = [];
  const written = new Set();
  const opts = { dryRun, changed, written, sources, dynamicLabels };
  await generateConfig(opts);
  await generateRuntimeData(opts);
  await generateSectionPages(opts);
  await generateSpotPages(opts);
  await removeStaleGeneratedArtifacts(opts);
  return changed;
}

async function main() {
  const command = process.argv[2];
  if (!command) {
    usage();
    process.exit(2);
  }
  if (command === "generate") {
    const changed = await generateAll();
    if (changed.length > 0) console.log(`generated ${changed.length} i18n artifact(s)`);
    return;
  }
  if (command === "check") {
    const changed = await generateAll({ dryRun: true });
    if (changed.length > 0) {
      console.error("i18n artifacts are out of date:");
      for (const file of changed) console.error(`- ${file}`);
      process.exit(1);
    }
    return;
  }
  usage();
  process.exit(2);
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
