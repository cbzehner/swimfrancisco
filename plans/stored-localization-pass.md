---
status: pending
gaps: []
edge_cases: []
progress: []
last_review: null
iterations: 0
no_progress_count: 0
started_at: null
---

# Stored Localization Pass

## Goal

Ship real localized Swim Francisco pages for the San Francisco language-access set:
English, Spanish, Chinese, Filipino/Tagalog, and Vietnamese.

Sources:
- SF Planning says public-serving departments translate important service/program material into Chinese, Filipino, and Spanish: https://sfplanning.org/policies/language-assistance
- The amended San Francisco Language Access Ordinance defines required languages as Chinese, Spanish, Filipino, and other qualifying languages, and notes Vietnamese as a significant LEP language group: https://media.api.sf.gov/documents/Language_Access_Ordinance-_Amended_June_2024.pdf

Assumption: implement Chinese as Traditional Chinese (`zh-Hant`) for this pass, matching the current site locale and SF public-facing norms.

## Product Scope

Translate and localize:
- Global navigation, board, map, filters, buttons, status labels, footer.
- Time-travel / plan-ahead headings, including the cute banner messages.
- Dynamic status copy such as "Closes 6:30 PM", "Opens MON 7:00 AM", "Schedule starts Jun 7".
- Spot detail SEO titles, meta descriptions, social titles/descriptions.
- Spot detail labels, weekday names, date formatting, connector words, closure banners, source labels.
- Spot editorial prose and summaries where they exist.

Keep canonical:
- Addresses, proper place names, URLs, facility names, fees unless the fee label itself is prose.
- Schedule facts, sessions, closures, coordinates, access classifications, source URLs.

## Architecture

Use stored translation sources, generated localized routes.

1. Keep canonical spot facts in `content/spots/*.md`.
2. Store locale copy in committed catalogs:
   - `i18n/ui/<locale>.toml` for UI/status/SEO/time-travel strings.
   - `i18n/spots/<locale>.toml` for per-spot localized title overrides, summaries, SEO copy, and markdown body copy.
   - `i18n/glossary.toml` for terms that must stay consistent across languages.
   - `i18n/translation-notes.md` for model, date, prompt policy, and reviewer notes.
3. Generate build-facing artifacts from those catalogs:
   - Zola `[translations]` blocks in `config.toml`, or a checked generated config fragment if Zola constraints make direct generation cleaner.
   - `content/spots/<slug>.<locale>.md` stubs containing only route metadata and optional localized body copied from `i18n/spots/<locale>.toml`.
   - Runtime JS i18n JSON/template data from the same UI catalog.
4. Read the locale list from one source in `config.toml` / `config.extra.languages`; templates and generators must not hardcode `["es", "zh-Hant", "fil", "vi"]`.

Complexity guard: do not introduce a runtime i18n framework. This is a static site. Use small scripts, TOML catalogs, existing Zola `trans()`, `load_data`, and direct JS helpers.

## LLM Translation Workflow

1. Extract all English source strings into stable keys with context comments.
2. Build one prompt per locale from:
   - Source strings.
   - Spot prose.
   - Glossary.
   - Placeholder rules.
   - Tone: useful, local, concise; preserve the playful time-travel headings without literal machine translation.
3. Run the one-time LLM translation pass and save outputs directly to `i18n/ui/<locale>.toml` and `i18n/spots/<locale>.toml`.
4. Validate automatically:
   - Every source key exists in every locale.
   - Placeholders are preserved.
   - No empty translations.
   - No obvious English fallback in known localized UI surfaces.
5. Spot-check manually:
   - One pool and one open-water spot per locale.
   - Time-travel banner messages.
   - Status rows for open, closed, pre-season, post-season, no schedule, and access-hours-only states.

## Implementation Phases

### Phase 1: Catalog And Locale Registry

Acceptance criteria:
- Locale metadata lives in one source and drives the language switcher, hreflang output, generator, and tests.
- UI keys include missing strings for statuses, date/weekday labels, SEO templates, conjunctions, and time-travel headings.
- Existing `config.toml` translations are migrated or generated from the new source without losing keys.

Verification:
- `node scripts/check-i18n.mjs`
- `zola build --output-dir /tmp/swimfrancisco-zola-build --force`

### Phase 2: Dynamic Status Localization

Acceptance criteria:
- `board.mjs` returns structured status/next data, not display-ready English sentences.
- `status.js` formats messages through i18n keys at the DOM boundary.
- Time-travel labels and cute headings use stored locale copy with no hardcoded English fallback in production paths.
- Dates and weekdays use locale-aware formatting or catalog labels.

Verification:
- JS unit tests cover all status message variants in at least English and Spanish.
- Browser smoke confirms `/es/` and `/vi/` do not hydrate English status strings.

### Phase 3: Spot Detail Localization

Acceptance criteria:
- Spot detail title/meta/social copy uses localized SEO templates.
- Build-time labels for "Schedule starts/ended", weekdays, month names, "and", and note text are localized.
- Spot prose comes from stored per-locale spot catalogs when present, otherwise falls back intentionally to canonical English.
- Proper names and factual schedule data remain canonical.

Verification:
- Render tests for `/es/spots/garfield-pool/`, `/zh-Hant/spots/aquatic-park/`, `/fil/spots/balboa-pool/`, and `/vi/spots/ocean-beach/`.
- Assertions include title, meta description, a schedule status phrase, weekday labels, and body/prose behavior.

### Phase 4: Generator Cleanup

Acceptance criteria:
- Generator parses TOML with a real parser or strict safe serializer.
- Generator accepts an output root so tests can build in a temp copy without mutating the repo root.
- Generated stubs are either ignored and regenerated in build/deploy, or committed by explicit decision. Stored translations remain committed either way.
- Locale filters use suffix matching, not substring matching.

Verification:
- Running pytest does not change `git status`.
- Build scripts and deploy scripts run generation before Zola.

### Phase 5: SEO And Regression Tests

Acceptance criteria:
- Every localized page has `rel="alternate"` links for all locales plus `x-default`.
- Language switcher URLs match the hreflang URLs.
- Catalog parity tests prevent missing JS/template keys.
- Render tests catch English leakage for agreed UI strings.

Verification:
- `uv --project schedule-tools run pytest tests/test_site_render.py`
- `node --test tests/js/*.test.mjs`
- `zola build --output-dir /tmp/swimfrancisco-zola-build --force`
- Manual browser pass for one desktop and one mobile viewport.

## Out Of Scope

- Live machine translation at request time.
- Translating third-party source names, addresses, official facility names, or external websites.
- Full professional translation vendor workflow.
- RTL support until an RTL language is added.

## Risks

- LLM translations may sound generic or use regionally odd phrasing. Mitigation: glossary, tone instructions, targeted spot checks, and stored notes.
- Chinese language choice is broad. Mitigation: ship `zh-Hant` for this pass and document why.
- English leakage tests can overfit. Mitigation: test known UI/status strings rather than banning all English globally, because proper nouns and facility names remain English.
