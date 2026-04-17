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
last_review: 2026-04-16T19:43:30-07:00
iterations: 10
no_progress_count: 0
started_at: 2026-04-16T19:04:36-07:00
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
