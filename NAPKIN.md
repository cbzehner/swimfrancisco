# Napkin Runbook

## Curation Rules
- Re-prioritize on every read.
- Keep recurring, high-value notes only.
- Max 10 items per category.
- Each item includes date + "Do instead".

## Execution & Validation (Highest Priority)
1. **[2026-04-17] Stop stale `devenv` processes with the built-in command first**
   Do instead: run `devenv processes down` from the repo root before falling back to manual `pkill` cleanup.
2. **[2026-04-17] Port `8787` belongs to `wrangler dev` via `workerd` in this repo**
   Do instead: if `devenv processes down` shows nothing but `http://localhost:8787/` is still live, inspect `lsof -nP -iTCP:8787 -sTCP:LISTEN` and kill the lingering `workerd` PID.
3. **[2026-04-17] Use `devenv up` for live UI review, not a standalone static server**
   Do instead: run `devenv up`, trigger `http://localhost:8787/__scheduled`, and inspect the board through `http://localhost:8787` so the site and Worker are reviewed together in the same-origin shape used by the project.

## Shell & Command Reliability
1. **[2026-04-17] `schedules` CLI does not autoload `.env`**
   Do instead: prefix with `set -a && source .env && set +a &&` when running `uv run schedules extract` or `uv run schedules debug bakeoff` or any provider call, or the run fails with `GOOGLE_API_KEY is not set.`.

## Domain Behavior Guardrails
1. **[2026-04-20] `content/spots/*.md` is the source of truth; `data/<slug>/<date>-<sha12>/` is a regeneration aid**
   Do instead: treat checked-in markdown as authoritative. Each per-review directory holds `source.pdf`, per-provider JSON, and `reviewed.json` (present ⇔ human-approved). Every new PDF sha256 requires a fresh human pass via `schedules review` — there is no auto-ratification.
2. **[2026-04-17] Do not publish stale Mission or Sava schedules**
   Do instead: leave `mission-community-pool` and `sava-pool` skipped until the official facility pages publish a current schedule PDF, then review that new hash.
3. **[2026-04-17] SFRP vocabulary: REC/FAMILY SWIM is one program, not two**
   Do instead: always map REC SWIM, RECREATION SWIM, REC/FAMILY SWIM, FAMILY SWIM to `family_swim`. `open_swim` is no longer in the enum. Instructor-led programs (WATER/DEEP WATER/SELF GUIDED EXERCISE, AEROBICS, MASTERS, SYNCHRO, PIRANHAS, WATER POLO, HOCKEY) are ignored entirely; SFUSD classes become closure entries.

## User Directives

## Conventions

- **Config formats**: TOML for human-authored config (Zola frontmatter, `pyproject.toml`, `config.toml`, `src/schedules/registry.toml`). JSON for machine-generated data (`data/**/*.json`). YAML only where a vendor tool requires it (`devenv.yaml`). New files follow this rule.
