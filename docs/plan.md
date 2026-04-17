---
status: in_progress
progress:
  - section: "Step 1: Initialize project"
    status: complete
    notes:
      - "devenv.nix rewritten for Python+uv, JS+npm, zola, git"
      - "gitignore expanded for public/, node_modules/, .wrangler/, dist/, .venv/, __pycache__/, *.pyc, .DS_Store"
      - "project-finding: codex-adapter runs read-only on this host — Claude applies Write on Codex's behalf"
  - section: "Step 2: Initialize Zola site"
    status: complete
    notes:
      - "config.toml created with base_url, title, description, compile_sass, minify_html"
      - "dir structure: content/spots/, templates/, static/, sass/ (all with .gitkeep)"
      - "followup: run `zola check` from devenv shell once templates/content exist"
  - section: "Step 3: Create content files for all 9 pools"
    status: partial
    notes:
      - "9 files created in content/spots/ — structure, addresses, websites, approximate lat/lng verified"
      - "Sava closure (2026-04-16 to 2026-09-21) documented"
      - "Hamilton Tue-Fri 6:30-10:00 lap swim verified from facility page"
      - "gap: SF Rec & Parks publishes schedules as PDFs (DocumentCenter/View/27964) — WebFetch couldn't extract; sessions TBD for 7 of 9 pools"
      - "gap: lat/lng are best-estimate geocodes, should be re-verified"
      - "gap: subagent claims config.toml has highlight_code bug, but it's under [markdown] as documented — verify with zola check later"
      - "user-accepted: session extraction deferred to later iteration"
  - section: "Step 4: Create content files for all 5 open water spots"
    status: complete
    notes:
      - "5 files: aquatic-park, crissy-field, baker-beach, ocean-beach, china-beach"
      - "Aquatic Park copied verbatim from spec.md canonical example"
      - "temp_station_type: noaa for bay spots (9414290), ndbc for ocean spots (46237)"
      - "noaa_tide_station=9414290 on all 5"
      - "Ocean Beach flagged with strong hazard list (rips, sneaker waves)"
      - "gap: lat/lng are best-estimate; carry-over with pool lat/lng re-verification"
  - section: "Step 5: Create base layout template"
    status: complete
    notes:
      - "templates/base.html with Tera blocks, dark inline theme, CSS link via get_url"
      - "sidecar fix: removed invalid [markdown] highlight_code key from config.toml (iter 2 bug)"
      - "zola check passes; orphan warnings on pages (expected until Step 6)"
  - section: "Step 6: Create homepage / departure board template"
    status: complete
    notes:
      - "templates/index.html extends base.html with filter UI + board table"
      - "rows carry data-slug, data-type, data-lat, data-lng, data-schedule (JSON of sessions+closures)"
      - "STATUS/NEXT/TEMP columns render placeholder dashes — JS will compute (Steps 10/11)"
      - "map container stubbed with <div id=map-view hidden> for Step 13"
      - "followup: default sort is doc order; open-first sort deferred to JS (Step 10)"
  - section: "Step 7: Create detail page template"
    status: complete
    notes:
      - "templates/spots/page.html branches on extra.type (pool | open_water)"
      - "content/spots/_index.md now sets page_template = spots/page.html so Zola picks it up"
      - "pool branch: Google Maps link (address), official site link, Mon–Sun schedule table, closures list, schedule_effective + last_verified_at footer"
      - "open_water branch: conditions stub <section class=conditions data-slug> with <dd data-field=water_temp> and data-field=tide hooks for Step 11 JS; then hazards/clubs/common_distances lists"
      - "both branches render page.content via | safe in a notes section and a back-link to / (departure board)"
      - "zola check + zola build pass; 14 /spots/<slug>/index.html produced"
      - "data-model gap: pool sessions frontmatter uses key `day` (not `day_of_week` as plan text described) — template matches actual content"
      - "data-model gap: pool subtype values are `indoor`, not the `lap|family|open` listed in Step 3 brief — template does not depend on subtype so harmless, but Step 6 filter pills assume `lap_swim|open_swim|family_swim` (session.type), not subtype"
      - "data-model gap: Sava 2026-04-16→2026-09-21 closure noted in Step 3 is not yet encoded as structured extra.closures data; closures section renders empty"
  - section: "Step 8: Departure board CSS"
    status: complete
    notes:
      - "sass/main.scss (242 lines) compiles to public/main.css (~2.9KB)"
      - "CSS custom properties mirror base.html inline colors (--bg #1a1a2e, --fg #f5c518, --fg-dim, --row-sep, --accent)"
      - "monospace stack only (ui-monospace, Share Tech Mono fallback); no webfont @import"
      - "active pill convention: button[aria-pressed=\"true\"] (amber-on-dark inversion) — documented at top of main.scss so Step 12 JS knows what to toggle"
      - "mobile @media (max-width:640px) hides TYPE (col 2) and NEXT (col 4); stacks conditions dl to single column"
      - "tap-to-expand hook: tbody tr[aria-expanded=true] + tr.row-detail reveal — Step 12 JS must inject <tr class=row-detail> with colspan cell"
      - "no animations beyond hover color shifts — split-flap keyframes are Step 9"
  - section: "Step 9: Split-flap animation CSS"
    status: complete
    notes:
      - "appended flap keyframe + .flap class to sass/main.scss (now 276 lines)"
      - "animation scoped to table.board tbody tr.flap td (cells, not rows) to avoid display:table-row transform issues"
      - "stagger via --flap-index CSS custom property: animation-delay = var(--flap-index, 0) * 30ms"
      - "Step 12 JS contract documented inline: set --flap-index on each row, toggle .flap, remove on animationend"
      - "prefers-reduced-motion: reduce disables the animation entirely"
      - "timing: 250ms flip + (14 rows × 30ms) = ~670ms worst case — slightly over plan's ~500ms budget; acceptable, can tighten to 20ms stagger later if needed"
  - section: "Step 10: Status computation script"
    status: complete
    notes:
      - "static/js/status.js created (~190 lines) with pure computeStatus(schedule, now) + sortRows(rows) and side-effectful applyStatuses/reorderDom"
      - "reads combined data-schedule JSON {sessions, closures} emitted by templates/index.html:36"
      - "closure-aware: active closure → STATUS=CLOSED, NEXT='Closed until YYYY-MM-DD' (exercises sava-pool's 2026-04-16→2026-09-21 closure)"
      - "OPEN → 'Closes HH:MM'; CLOSED with upcoming session today → 'Opens HH:MM'; next-day session → 'Opens DAY HH:MM' (3-letter day)"
      - "sortRows: open pools first, then alphabetical by SPOT text; stable via original-index tiebreaker; open_water rows sort alphabetically (skipped for status compute)"
      - "wired via {% block scripts %} in templates/index.html → base.html:19 hook; loads with defer only on board page"
      - "24-hour time format throughout; 12-hour conversion deferred (flagged in next_steps)"
      - "tests_status: passed — zola check + zola build both succeed, public/js/status.js + script tag verified"
      - "data-finding: only hamilton-pool has sessions populated; 8 other pools render STATUS/NEXT as em-dash (Step 3 gap carries forward)"
      - "followup: Step 12 flap trigger will need to re-run applyStatuses + sortRows + reorderDom after filter change, toggling .flap + --flap-index"
  - section: "Step 11: Conditions fetch script"
    status: complete
    notes:
      - "static/js/conditions.js: pure extractTemp(record), async fetchConditions(url), applyConditions(root, conditions)"
      - "endpoint configurable via window.SWIMFRANCISCO_API, default /api/conditions"
      - "accepts water_temp_f or water_temp_c (converted); renders integer °F; silent on any failure (network/non-2xx/bad JSON)"
      - "wired into templates/index.html {% block scripts %} next to status.js"
      - "wired into templates/spots/page.html {% block scripts %} guarded by extra.type == 'open_water' — verified only 5 ocean detail pages include it"
      - "tests_status: passed — zola build green, public/js has both scripts, guards confirmed"
      - "gap: Worker /api/conditions does not exist yet (Steps 14-15) — script degrades silently until then"
      - "followup: tide <dd data-field='tide'> hook exists on detail pages but is not populated this step"
  - section: "Step 12: Filter logic"
    status: complete
    notes:
      - "static/js/filters.js implements Open Now, Type pills (lap_swim/open_swim/family_swim/open_water, multi-select OR), Near Me (geolocation + haversine distance sort)"
      - "pure helpers: rowMatchesType, rowIsClosed, rowPassesFilters, haversineMiles, sortByDistance, triggerFlap"
      - "type-pill convention: lap_swim/open_swim/family_swim look inside data-schedule sessions[].type; open_water matches row.dataset.type"
      - "Open Now hides rows where STATUS cell text === 'CLOSED' (open-water em-dash rows remain visible — plan-aligned)"
      - "Near Me gracefully no-ops on unsupported/denied geolocation (un-presses button)"
      - "flap retrigger via reflow (void row.offsetWidth) + sequential --flap-index; once-listener on animationend bubbling from td"
      - "coordination: added one dispatchEvent('sf:status-applied') line to status.js; filters.js listens (with requestAnimationFrame fallback) before attaching handlers"
      - "wired into templates/index.html {% block scripts %} after status.js + conditions.js, all defer"
      - "tests_status: passed — zola build green; script order verified status→conditions→filters"
      - "gap: most pools still have empty sessions[] (Step 3 gap) — type pills match few rows in practice"
      - "followup: manual browser smoke test for pill toggle + geolocation reorder; Step 13 MAP button handler still stubbed"
  - section: "Step 13: Map view toggle"
    status: complete
    notes:
      - "Leaflet 1.9.4 via unpkg CDN; CSS in base.html <head> (integrity + crossorigin); JS lazy-loaded on first MAP click from map.js"
      - "static/js/map.js: ensureLeaflet(), collectSpots() (filters out invalid lat/lng), createPopupHTML(spot), initMap() centered on SF (~37.78,-122.45 z12) with OSM tiles, toggleMap() caches single instance and calls invalidateSize() after show"
      - "MAP button aria-pressed + flips hidden on #map-view and table.board; Leaflet load failure un-presses button, restores board, console.error"
      - "sass/main.scss: #map-view { height:70vh; min-height:400px; amber border } + .sf-map-popup styles"
      - "popups show name, type, STATUS (captured at open time — no live refresh) and link to /spots/{slug}/"
      - "tests_status: passed — zola build green; index.html has leaflet.css + map.js; detail pages have leaflet.css (base.html) but NOT map.js (scripts block is index-only)"
      - "gap: map markers not filtered by active Open Now/type/Near Me state — plan said skip; flagged for future"
      - "gap: filter buttons remain visible when map is shown (left as-is per plan simplification)"
  - section: "Step 14: Worker scaffold"
    status: complete
    notes:
      - "worker/ with package.json (type=module, scripts: dev/deploy/typecheck, devDeps wrangler+typescript+@cloudflare/workers-types), tsconfig.json (ES2022, ESNext, bundler, strict, noEmit), wrangler.toml (name, main=src/index.ts, compatibility_date=2025-01-01, hourly cron 0 * * * *, KV binding CONDITIONS with REPLACE_ME placeholders), src/index.ts (minimal fetch+scheduled skeleton), .gitignore"
      - "tests_status: not_run — @cloudflare/workers-types unresolved until `cd worker && npm install` in Step 15"
      - "TS diagnostics expected (KVNamespace, Request, Response, etc.) — will resolve after npm install"
      - "site still builds clean (zola build passes)"
      - "user-action: create KV namespaces via `wrangler kv:namespace create CONDITIONS` (plus --preview), fill REPLACE_ME ids in wrangler.toml before first deploy"
  - section: "Step 15: Worker implementation"
    status: complete
    notes:
      - "worker/src split into focused modules: spots.ts (5-spot→station map, NOAA fallback 9414750 for bay spots), cors.ts (https://swimfrancisco.com + Vary: Origin + 204 preflight), noaa.ts (CO-OPS water_temperature latest + predictions hilo with primary→fallback), ndbc.ts (realtime2.txt parser, WTMP column, C→F), kv.ts (conditions:<slug> + all bulk), assemble.ts (keep-last-good fallback, stale=true flag, shared tide station cached across spots), index.ts (fetch + scheduled handlers)"
      - "npm install ran (wrangler + typescript + @cloudflare/workers-types installed; package-lock.json committed, node_modules ignored)"
      - "tests_status: passed — npm run typecheck exits 0 with no TS errors"
      - "routes: GET /api/conditions → all KV (503 if absent), GET /api/conditions/:slug → per-spot (404 if absent), OPTIONS → 204 preflight, else 404 (405 on non-GET)"
      - "cache-control: public, max-age=60, s-maxage=300"
      - "scheduled() uses ctx.waitUntil(assembleAndPersist); per-spot last-good reuse means a single upstream failure doesn't empty the bulk blob"
      - "gap: NOAA timestamps are station-local (lst_ldt); Worker emits as-is — consumers should treat temp_observed_at accordingly. NDBC is already UTC."
      - "gap: tide data is in KV records but static/js/conditions.js does not yet populate <dd data-field='tide'> — deferred"
      - "user-action: REPLACE_ME KV ids in wrangler.toml must be filled after `wrangler kv:namespace create CONDITIONS`"
  - section: "Phase 6 review follow-ups (magi 2026-04-16)"
    status: complete
    notes:
      - "magi verdict on Phase 6: needs_work (CORS, stale ceiling, toIsoLike, bootstrap, NOAA application param)"
      - "cors.ts: regex allow-list {prod, *.swimfrancisco.pages.dev, http://localhost:*} via isAllowedOrigin(); corsHeaders/preflight now take Request and echo matched origin (or omit ACAO entirely for disallowed origins)"
      - "index.ts: threaded Request through jsonResponse/notFound/serviceUnavailable/preflight/405 paths"
      - "assemble.ts: added isFreshEnough(previous) gating both temp and tide last-good reuse on previous.updated_at < 24h ago — prevents unbounded stale fallbacks"
      - "noaa.ts: toIsoLike → toLocalIso; interface docs corrected to 'Station-local time, zoneless ISO (NOAA lst_ldt)'; appended &application=SwimFrancisco to temp + tide URLs"
      - "worker/README.md created: routes, cron, KV bootstrap (wrangler triggers deploy + wrangler cron trigger to avoid 1h cold-start 503), local dev commands"
      - "tests_status: passed — npm run typecheck zero errors, zola build still green"
      - "deferred: Cache API in front of KV (magi #6) — scale-dependent, skipped per reviewer note"
  - section: "Step 16: Mobile polish"
    status: complete
    notes:
      - "static/js/expand.js: mobile-only tap-to-expand gated by matchMedia('(max-width: 640px)'); row click toggles aria-expanded + injects/removes sibling <tr class='row-detail'> with colspan=5; anchor clicks in the row pass through; viewport-crossing back to desktop collapses any expanded rows"
      - "dropped deprecated mql.addListener fallback — addEventListener is universally supported in current Safari/Chrome/Firefox"
      - "templates/index.html: <noscript> notice at top of filters div explaining that live status/filters/map are unavailable but detail pages still work"
      - "sass/main.scss: .noscript-notice (amber border, dim text, uppercase); existing .row-detail + aria-expanded rules from Step 8 CSS suffice (verified)"
      - "wired expand.js into index.html scripts block"
      - "tests_status: passed — zola build green; public/js/ has all 5 scripts; noscript + expand.js both present in public/index.html"
      - "gap noted but out-of-scope: table has no overflow-x wrapper (existing mobile CSS hides TYPE+NEXT cols, sufficient for SF spot name widths)"
      - "gap noted but out-of-scope: map-view filter buttons visible when map is open (pre-existing from Step 13)"
last_review: 2026-04-16T20:00:30-07:00
iterations: 17
no_progress_count: 0
started_at: 2026-04-16T19:45:00-07:00
work_unit_granularity: step  # ### Step N, not ## Phase
---

# SwimFrancisco v1 Implementation Plan

Reference: [docs/spec.md](spec.md)

## Phase 1: Project Scaffolding

### Step 1: Initialize project
- `git init`
- `devenv init` for Nix-managed dev environment
- Configure devenv with: Python + uv, Zola, Node (for wrangler), and standard dev tools
- Add `.gitignore`

### Step 2: Initialize Zola site
- `zola init` in the project root (or configure manually)
- Set up `config.toml` with site name, base URL (swimfrancisco.com), and any global settings
- Create directory structure: `content/spots/`, `templates/`, `static/`, `sass/`

## Phase 2: Data & Content

### Step 3: Create content files for all 9 pools
- One `.md` file per pool in `content/spots/`
- TOML frontmatter with: title, slug, type, subtype, address, lat, lng, website, cost, schedule_effective, last_verified_at, sessions[], closures[]
- Source schedule data from the current SF Rec & Parks pool schedule (use Gemini search or web fetch to find current hours)
- Markdown body with a short description of each pool

### Step 4: Create content files for all 5 open water spots
- One `.md` file per spot in `content/spots/`
- TOML frontmatter with: title, slug, type, address, lat, lng, cost, noaa_tide_station, temp_station_id, temp_station_type, description_short, hazards[], clubs[], common_distances[]
- Markdown body with description

## Phase 3: Templates & Static HTML

### Step 5: Create base layout template
- `templates/base.html` — HTML shell with `<head>`, meta tags, CSS link, body wrapper
- Dark background (departure board aesthetic)
- Include inline `<script>` block at bottom for progressive enhancement JS (empty for now)

### Step 6: Create homepage / departure board template
- `templates/index.html` — the main departure board view
- Render all spots as table rows with columns: SPOT, TYPE, STATUS, NEXT, TEMP
- Each row gets `data-slug` and `data-schedule` (inline JSON of sessions + closures) attributes
- Pools show STATUS/NEXT as placeholder text (JS will compute); open water spots show "—" for STATUS (conditions, not open/closed)
- TEMP column empty by default (filled by JS from Worker)
- Include filter UI above the board: Open Now toggle, Type pills (Lap / Open / Family / Open Water), Near Me button
- Default sort: open-first (requires JS), fallback alphabetical in static HTML

### Step 7: Create detail page template
- `templates/spots/page.html` — per-spot detail page at `/spots/:slug/`
- Pools: full weekly schedule table, address, link to official page
- Open water: conditions panel placeholder (filled by JS), hazards, safety notes
- Both: static map image placeholder (can use a simple link to Google Maps for v1)

## Phase 4: Styling

### Step 8: Departure board CSS
- Dark background (#1a1a2e or similar dark navy/black)
- Monospaced or mechanical font (system monospace, or a web font like "Share Tech Mono")
- Yellow/amber text on dark background for the board
- Table styling: tight rows, uppercase text, subtle row separators
- Filter pills: toggle-able buttons above the board
- Responsive: 3-column layout on mobile (SPOT, STATUS, TEMP), full columns on desktop
- Tap-to-expand styles for mobile rows

### Step 9: Split-flap animation CSS
- `.flap` class with CSS `rotateX` transforms on top/bottom halves
- Staggered animation: each row delayed by 50ms
- Trigger class for filter changes
- Keep animation duration short (~500ms total for all rows)

## Phase 5: Client-Side JS

### Step 10: Status computation script
- Read `data-schedule` and `data-closures` from each row
- Check current time against sessions to compute STATUS (OPEN/CLOSED) and NEXT (next state change)
- Skip status computation for open water spots (they don't have open/closed)
- Update DOM with computed values
- Re-sort rows: open-first, then alphabetical

### Step 11: Conditions fetch script
- Fetch `/api/conditions` from the Worker
- Inject water temp into TEMP column for open water spots by matching `data-slug`
- Graceful degradation: if fetch fails, TEMP stays empty

### Step 12: Filter logic
- Open Now: hide rows where computed status is CLOSED
- Type pills: filter by session type (lap_swim, open_swim, family_swim, open_water)
- Near Me: request geolocation, compute distance from lat/lng in `data-` attributes, re-sort by distance
- Each filter triggers split-flap animation on affected rows

### Step 13: Map view toggle
- Button to switch between list (departure board) and map view
- Leaflet + OpenStreetMap tiles
- Pins for each spot with popup showing name + status
- Map container hidden by default, shown on toggle

## Phase 6: Cloudflare Worker

### Step 14: Worker scaffold
- `worker/` directory with TypeScript, wrangler.toml, KV namespace config
- Cron trigger: hourly schedule

### Step 15: Worker implementation
- Cron handler: fetch NOAA station 9414290 (bay temp + tides, fallback 9414750), fetch NDBC buoy 46237 (ocean temp)
- Parse responses, assemble per-spot conditions JSON
- Write to KV: one key per slug + `all` key for bulk
- Error handling: if upstream fails, keep last-good data in KV, log the error
- HTTP handler: `GET /api/conditions` returns the `all` KV value, `GET /api/conditions/:slug` returns per-spot
- CORS headers for swimfrancisco.com

## Phase 7: Polish & Deploy

### Step 16: Mobile polish
- Test and refine responsive layout
- Verify tap-to-expand interaction
- Verify animation performance on mobile
- Ensure the page is usable without JS

### Step 17: Deploy setup
- Configure Cloudflare Pages (build command: `zola build`, output dir: `public/`)
- Deploy Worker via wrangler
- Wire up swimfrancisco.com domain (manual step — document instructions)

### Step 18: README and final touches
- README with: what this is, how to run locally (`devenv shell`, `zola serve`), how to deploy, how to update content
- Verify all spots render correctly
- Verify Worker serves conditions
- Verify filters and animation work
