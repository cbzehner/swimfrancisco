import { mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { parse, stringify } from "smol-toml";

const ROOT = process.cwd();
const CONFIG_PATH = path.join(ROOT, "config.toml");
const SOURCE_DIR = path.join(ROOT, "i18n");
const UI_DIR = path.join(SOURCE_DIR, "ui");
const SPOTS_DIR = path.join(SOURCE_DIR, "spots");
const SECTIONS_DIR = path.join(SOURCE_DIR, "sections");
const SOURCE_LOCALES_PATH = path.join(SOURCE_DIR, "locales.toml");
const SOURCE_DYNAMIC_LABELS_PATH = path.join(SOURCE_DIR, "dynamic-labels.toml");
const DATA_LOCALES_PATH = path.join(ROOT, "data", "locales.toml");
const DATA_I18N_DIR = path.join(ROOT, "data", "i18n");
const DATA_DYNAMIC_LABELS_TOML_PATH = path.join(DATA_I18N_DIR, "dynamic-labels.toml");
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

function usage() {
  console.error("Usage: node scripts/generate-i18n.mjs <extract|generate|check>");
}

async function readToml(file) {
  return parse(await readFile(file, "utf8"));
}

function sortedObject(object) {
  return Object.fromEntries(Object.entries(object || {}).sort(([a], [b]) => a.localeCompare(b)));
}

function tomlText(object) {
  return `${stringify(object).trim()}\n`;
}

function parseFrontMatter(text, file) {
  const match = /^\+\+\+\n([\s\S]*?)\n\+\+\+\n?([\s\S]*)$/.exec(text);
  if (!match) throw new Error(`${file} is missing TOML front matter`);
  return { front: parse(match[1]), body: match[2].trim() };
}

async function writeIfChanged(file, text, { dryRun = false, changed = [] } = {}) {
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

async function validateCatalogFiles({ allCodes, translatedCodes }) {
  const catalogSets = [
    { dir: UI_DIR, label: "i18n/ui", expected: allCodes },
    { dir: SPOTS_DIR, label: "i18n/spots", expected: translatedCodes },
    { dir: SECTIONS_DIR, label: "i18n/sections", expected: translatedCodes },
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

async function loadDynamicLabels() {
  if (!existsSync(SOURCE_DYNAMIC_LABELS_PATH)) {
    throw new Error("i18n/dynamic-labels.toml is missing");
  }
  return readToml(SOURCE_DYNAMIC_LABELS_PATH);
}

function dynamicLabelMap(dynamicLabels) {
  const byKind = {};
  for (const label of dynamicLabels.labels || []) {
    byKind[label.kind] ||= { by_code: {}, by_source: {} };
    byKind[label.kind].by_source[label.source] = {
      code: label.code,
      translation_key: label.translation_key,
    };
    byKind[label.kind].by_code[label.code] ||= {
      translation_key: label.translation_key,
      sources: [],
    };
    byKind[label.kind].by_code[label.code].sources.push(label.source);
  }
  return byKind;
}

function dynamicLabelData(dynamicLabels) {
  return {
    labels: dynamicLabels.labels || [],
    ...dynamicLabelMap(dynamicLabels),
  };
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
    if (front.extra?.localized_from) continue;
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

  for (const label of dynamicLabels.labels || []) {
    if (defaultKeys.has(label.translation_key)) runtimeKeys.add(label.translation_key);
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
    if (!text.includes('load_data(path="data/locales.toml")')) {
      throw new Error(`${path.relative(ROOT, file)} must load data/locales.toml for locale metadata`);
    }
  }

  const localeAlternation = codes.filter((code) => code !== "en").map((code) => code.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
  if (!localeAlternation) return;
  const hardcodedLocalePattern = new RegExp(`(lang|hreflang|og_locale|locale|code)\\s*(==|=|:)\\s*["'](?:${localeAlternation})["']`);
  for (const file of requiredConsumers) {
    const text = await readFile(file, "utf8");
    if (hardcodedLocalePattern.test(text)) {
      throw new Error(`${path.relative(ROOT, file)} appears to hardcode a locale instead of using data/locales.toml`);
    }
  }
}

async function extractCatalogs() {
  const config = await readToml(CONFIG_PATH);
  const existingLocaleData = existsSync(DATA_LOCALES_PATH)
    ? await readToml(DATA_LOCALES_PATH)
    : { locales: [] };
  const existingLocaleByCode = new Map((existingLocaleData.locales || []).map((locale) => [locale.code, locale]));

  const locales = [
    {
      ...(existingLocaleByCode.get(config.default_language) || {}),
      code: config.default_language,
      label: existingLocaleByCode.get(config.default_language)?.label || config.default_language.toUpperCase(),
      og_locale: existingLocaleByCode.get(config.default_language)?.og_locale || "en_US",
      is_default: true,
      title: config.title,
      description: config.description,
    },
  ];

  for (const [code, language] of Object.entries(config.languages || {})) {
    const existing = existingLocaleByCode.get(code) || {};
    locales.push({
      ...existing,
      code,
      label: existing.label || code.toUpperCase(),
      og_locale: existing.og_locale || `${code}_${code.toUpperCase()}`,
      is_default: false,
      title: language.title,
      description: language.description,
    });
  }

  await mkdir(UI_DIR, { recursive: true });
  await mkdir(SPOTS_DIR, { recursive: true });
  await mkdir(SECTIONS_DIR, { recursive: true });
  await writeFile(SOURCE_LOCALES_PATH, tomlText({ locales }));
  await writeFile(path.join(UI_DIR, `${config.default_language}.toml`), tomlText(sortedObject(config.translations || {})));

  for (const [code, language] of Object.entries(config.languages || {})) {
    await writeFile(path.join(UI_DIR, `${code}.toml`), tomlText(sortedObject(language.translations || {})));
  }

  const localeCodes = locales.filter((locale) => !locale.is_default).map((locale) => locale.code);
  const spotCatalogs = Object.fromEntries(localeCodes.map((code) => [code, { spots: {} }]));
  const files = await readdir(CONTENT_SPOTS_DIR);

  for (const file of files) {
    for (const code of localeCodes) {
      if (!file.endsWith(`.${code}.md`) || file.startsWith("_index.")) continue;
      const fullPath = path.join(CONTENT_SPOTS_DIR, file);
      const { front, body } = parseFrontMatter(await readFile(fullPath, "utf8"), fullPath);
      const localizedFrom = front.extra?.localized_from;
      if (!localizedFrom) throw new Error(`${file} is missing extra.localized_from`);
      const spot = {
        title: front.title,
        slug: front.slug || localizedFrom,
        ...sortedObject(Object.fromEntries(
          Object.entries(front.extra || {}).filter(([key]) => key !== "localized_from"),
        )),
      };
      if (body) spot.body = body;
      spotCatalogs[code].spots[localizedFrom] = spot;
    }
  }

  for (const [code, catalog] of Object.entries(spotCatalogs)) {
    catalog.spots = sortedObject(catalog.spots);
    await writeFile(path.join(SPOTS_DIR, `${code}.toml`), tomlText(catalog));
  }

  for (const code of localeCodes) {
    const sections = {};
    for (const [sectionKey, target] of Object.entries(SECTION_TARGETS)) {
      const sectionPath = path.join(CONTENT_DIR, `${target}.${code}.md`);
      if (!existsSync(sectionPath)) throw new Error(`${path.relative(ROOT, sectionPath)} does not exist`);
      sections[sectionKey] = parseFrontMatter(await readFile(sectionPath, "utf8"), sectionPath).front;
    }
    await writeFile(path.join(SECTIONS_DIR, `${code}.toml`), tomlText({ sections }));
  }
}

async function clearExtractedCatalogs() {
  await rm(SOURCE_LOCALES_PATH, { force: true });
  await rm(UI_DIR, { recursive: true, force: true });
  await rm(SPOTS_DIR, { recursive: true, force: true });
  await rm(SECTIONS_DIR, { recursive: true, force: true });
}

async function loadSources() {
  const locales = await readToml(SOURCE_LOCALES_PATH);
  const ui = {};
  for (const code of sourceLocaleCodes(locales)) {
    ui[code] = await readToml(path.join(UI_DIR, `${code}.toml`));
  }
  return { locales, ui };
}

async function validateSources() {
  const { locales, ui } = await loadSources();
  const dynamicLabels = await loadDynamicLabels();
  const defaults = locales.locales.filter((locale) => locale.is_default);
  if (defaults.length !== 1) throw new Error("i18n/locales.toml must define exactly one default locale");

  const codes = sourceLocaleCodes(locales);
  const duplicateCodes = codes.filter((code, index) => codes.indexOf(code) !== index);
  if (duplicateCodes.length > 0) {
    throw new Error(`i18n/locales.toml contains duplicate locale code(s): ${duplicateCodes.join(", ")}`);
  }
  await validateLocaleRegistryConsumers(codes);

  const nonDefaultCodes = nonDefaultLocaleCodes(locales);
  await validateCatalogFiles({ allCodes: codes, translatedCodes: nonDefaultCodes });

  const defaultKeys = Object.keys(ui[defaults[0].code] || {}).sort();
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
      const defaultPlaceholders = placeholders(ui[defaults[0].code][key]);
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

  const seenDynamicLabels = new Set();
  const dynamicKeysByCode = new Map();
  const dynamicLabelsByKind = dynamicLabelMap(dynamicLabels);
  const dynamicLabelKinds = unique((dynamicLabels.labels || []).map((label) => label.kind)).sort();
  const missingDynamicKinds = REQUIRED_DYNAMIC_LABEL_KINDS.filter((kind) => !dynamicLabelKinds.includes(kind));
  if ((dynamicLabels.labels || []).length === 0 || missingDynamicKinds.length > 0) {
    throw new Error(
      `i18n/dynamic-labels.toml must define ${REQUIRED_DYNAMIC_LABEL_KINDS.join(", ")} label kinds; missing: ${missingDynamicKinds.join(", ") || "none"}`,
    );
  }
  const codePattern = /^[a-z][a-z0-9_]*$/;
  for (const label of dynamicLabels.labels || []) {
    if (!label.kind || !label.source || !label.code || !label.translation_key) {
      throw new Error("i18n/dynamic-labels.toml labels must include kind, source, code, and translation_key");
    }
    if (!codePattern.test(label.code)) {
      throw new Error(`i18n/dynamic-labels.toml has invalid code for ${label.kind}:${label.source}: ${label.code}`);
    }
    const identity = `${label.kind}:${label.source}`;
    if (seenDynamicLabels.has(identity)) throw new Error(`i18n/dynamic-labels.toml duplicates label: ${identity}`);
    seenDynamicLabels.add(identity);
    const codeIdentity = `${label.kind}:${label.code}`;
    const existingKey = dynamicKeysByCode.get(codeIdentity);
    if (existingKey && existingKey !== label.translation_key) {
      throw new Error(
        `i18n/dynamic-labels.toml maps ${codeIdentity} to both ${existingKey} and ${label.translation_key}`,
      );
    }
    dynamicKeysByCode.set(codeIdentity, label.translation_key);
    for (const code of codes) {
      if (!ui[code][label.translation_key]) {
        throw new Error(`i18n/dynamic-labels.toml references missing ${code} translation key: ${label.translation_key}`);
      }
    }
  }

  const extras = await canonicalSpotExtras(codes);
  const missingDynamicLabels = dynamicLabelRequirements(extras).filter(
    (requirement) => !dynamicLabelsByKind[requirement.kind]?.by_source?.[requirement.source],
  );
  if (missingDynamicLabels.length > 0) {
    const details = missingDynamicLabels
      .map((item) => `${item.kind}:${JSON.stringify(item.source)} in ${item.file}`)
      .join("; ");
    throw new Error(`i18n/dynamic-labels.toml is missing canonical display label(s): ${details}`);
  }
  const missingDynamicCodes = dynamicLabelRequirements(extras).filter(
    (requirement) => requirement.code && !dynamicLabelsByKind[requirement.kind]?.by_code?.[requirement.code],
  );
  if (missingDynamicCodes.length > 0) {
    const details = missingDynamicCodes
      .map((item) => `${item.kind}:${item.code} for ${JSON.stringify(item.source)} in ${item.file}`)
      .join("; ");
    throw new Error(`i18n/dynamic-labels.toml is missing canonical display code(s): ${details}`);
  }

  const requiredSections = Object.keys(SECTION_TARGETS).sort();
  for (const code of nonDefaultCodes) {
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

  const expectedSpotSlugs = await canonicalSpotSlugs(codes);
  for (const code of nonDefaultCodes) {
    const catalog = await readToml(path.join(SPOTS_DIR, `${code}.toml`));
    const slugs = unique(Object.keys(catalog.spots || {})).sort();
    const missing = expectedSpotSlugs.filter((slug) => !slugs.includes(slug));
    const extra = slugs.filter((slug) => !expectedSpotSlugs.includes(slug));
    if (missing.length || extra.length) {
      throw new Error(
        `i18n/spots/${code}.toml slug mismatch; missing: ${missing.join(", ") || "none"}; extra: ${extra.join(", ") || "none"}`,
      );
    }
  }
}

async function expectedGeneratedArtifacts() {
  const { locales } = await loadSources();
  const localeCodes = nonDefaultLocaleCodes(locales);
  const expected = new Set([
    path.relative(ROOT, DATA_LOCALES_PATH),
    path.relative(ROOT, DATA_DYNAMIC_LABELS_TOML_PATH),
    path.relative(ROOT, DATA_DYNAMIC_LABELS_JSON_PATH),
  ]);

  for (const code of sourceLocaleCodes(locales)) {
    expected.add(path.relative(ROOT, path.join(DATA_I18N_DIR, `${code}.json`)));
  }

  for (const code of localeCodes) {
    for (const target of Object.values(SECTION_TARGETS)) {
      expected.add(path.relative(ROOT, path.join(CONTENT_DIR, `${target}.${code}.md`)));
    }

    const catalog = await readToml(path.join(SPOTS_DIR, `${code}.toml`));
    for (const slug of Object.keys(catalog.spots || {})) {
      expected.add(path.relative(ROOT, path.join(CONTENT_SPOTS_DIR, `${slug}.${code}.md`)));
    }
  }

  return expected;
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

async function generatedSpotArtifactsOnDisk() {
  const artifacts = [];
  if (!existsSync(CONTENT_SPOTS_DIR)) return artifacts;
  for (const file of await readdir(CONTENT_SPOTS_DIR)) {
    if (!file.endsWith(".md") || file.startsWith("_index.")) continue;
    const fullPath = path.join(CONTENT_SPOTS_DIR, file);
    const { front } = parseFrontMatter(await readFile(fullPath, "utf8"), fullPath);
    if (front.extra?.localized_from) artifacts.push(path.relative(ROOT, fullPath));
  }
  return artifacts;
}

async function generatedRuntimeArtifactsOnDisk() {
  const artifacts = [];
  if (existsSync(DATA_LOCALES_PATH)) artifacts.push(path.relative(ROOT, DATA_LOCALES_PATH));
  if (!existsSync(DATA_I18N_DIR)) return artifacts;
  for (const file of await readdir(DATA_I18N_DIR)) {
    if (file.endsWith(".json") || file.endsWith(".toml")) {
      artifacts.push(path.relative(ROOT, path.join(DATA_I18N_DIR, file)));
    }
  }
  return artifacts;
}

async function removeStaleGeneratedArtifacts({ dryRun = false, changed = [] } = {}) {
  const expected = await expectedGeneratedArtifacts();
  const actual = [
    ...(await generatedRuntimeArtifactsOnDisk()),
    ...(await generatedSectionArtifactsOnDisk()),
    ...(await generatedSpotArtifactsOnDisk()),
  ];
  const stale = unique(actual.filter((file) => !expected.has(file))).sort();

  for (const file of stale) {
    changed.push(file);
    if (!dryRun) await rm(path.join(ROOT, file), { force: true });
  }
}

async function generateConfig({ dryRun = false, changed = [] } = {}) {
  const current = await readToml(CONFIG_PATH);
  const { locales, ui } = await loadSources();
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

  return writeIfChanged(CONFIG_PATH, tomlText(next), { dryRun, changed });
}

async function generateRuntimeData({ dryRun = false, changed = [] } = {}) {
  const { locales, ui } = await loadSources();
  const dynamicLabels = await loadDynamicLabels();
  const dynamicLabelPayload = dynamicLabelData(dynamicLabels);
  const defaultLocale = locales.locales.find((locale) => locale.is_default);
  const runtimeKeys = await runtimeTranslationKeys(ui[defaultLocale.code], dynamicLabels);
  await writeIfChanged(DATA_LOCALES_PATH, tomlText(locales), { dryRun, changed });
  if (!dryRun) await mkdir(DATA_I18N_DIR, { recursive: true });
  for (const code of sourceLocaleCodes(locales)) {
    const runtimeUi = Object.fromEntries(runtimeKeys.map((key) => [key, ui[code][key]]));
    const file = path.join(DATA_I18N_DIR, `${code}.json`);
    await writeIfChanged(file, `${JSON.stringify(runtimeUi, null, 2)}\n`, { dryRun, changed });
  }
  await writeIfChanged(DATA_DYNAMIC_LABELS_TOML_PATH, tomlText(dynamicLabelPayload), { dryRun, changed });
  await writeIfChanged(
    DATA_DYNAMIC_LABELS_JSON_PATH,
    `${JSON.stringify(dynamicLabelPayload, null, 2)}\n`,
    { dryRun, changed },
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

function sectionMarkdown(section) {
  return `+++\n${tomlText(section)}+++\n`;
}

async function generateSectionPages({ dryRun = false, changed = [] } = {}) {
  const { locales } = await loadSources();
  const localeCodes = nonDefaultLocaleCodes(locales);

  for (const code of localeCodes) {
    const catalog = await readToml(path.join(SECTIONS_DIR, `${code}.toml`));
    for (const [sectionKey, target] of Object.entries(SECTION_TARGETS)) {
      const section = catalog.sections?.[sectionKey];
      if (!section) throw new Error(`i18n/sections/${code}.toml is missing ${sectionKey}`);
      const file = path.join(CONTENT_DIR, `${target}.${code}.md`);
      await writeIfChanged(file, sectionMarkdown(section), { dryRun, changed });
    }
  }
}

async function generateSpotPages({ dryRun = false, changed = [] } = {}) {
  const { locales } = await loadSources();
  const localeCodes = nonDefaultLocaleCodes(locales);

  for (const code of localeCodes) {
    const catalogPath = path.join(SPOTS_DIR, `${code}.toml`);
    if (!existsSync(catalogPath)) continue;
    const catalog = await readToml(catalogPath);
    for (const [slug, spot] of Object.entries(catalog.spots || {})) {
      const file = path.join(CONTENT_SPOTS_DIR, `${slug}.${code}.md`);
      await writeIfChanged(file, spotMarkdown(slug, spot), { dryRun, changed });
    }
  }
}

async function generateAll({ dryRun = false } = {}) {
  await validateSources();
  const changed = [];
  await generateConfig({ dryRun, changed });
  await generateRuntimeData({ dryRun, changed });
  await generateSectionPages({ dryRun, changed });
  await generateSpotPages({ dryRun, changed });
  await removeStaleGeneratedArtifacts({ dryRun, changed });
  return changed;
}

async function main() {
  const command = process.argv[2];
  if (!command) {
    usage();
    process.exit(2);
  }
  if (command === "extract") {
    await clearExtractedCatalogs();
    await extractCatalogs();
    return;
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
