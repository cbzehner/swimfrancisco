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
   Do instead: prefix with `set -a && source .env && set +a &&` when running `uv run schedules extract` with `--compare-with` or any provider call, or the run fails with `GOOGLE_API_KEY is not set.`.

## Domain Behavior Guardrails
1. **[2026-04-17] Reviewed schedule truth lives in `data/adjudications/`, not in provider output**
   Do instead: when a pool has been manually checked, commit `data/adjudications/<slug>/<pdf_sha256>.json` and expect reruns to resolve as `provider=adjudicated`; treat `data/artifacts/` as disposable local review cache.
2. **[2026-04-17] Do not publish stale Mission or Sava schedules**
   Do instead: leave `mission-community-pool` and `sava-pool` skipped until the official facility pages publish a current schedule PDF, then adjudicate that new hash.
3. **[2026-04-17] SFRP vocabulary: REC/FAMILY SWIM is one program, not two**
   Do instead: always map REC SWIM, RECREATION SWIM, REC/FAMILY SWIM, FAMILY SWIM to `family_swim`. `open_swim` is no longer in the enum. Instructor-led programs (WATER/DEEP WATER/SELF GUIDED EXERCISE, AEROBICS, MASTERS, SYNCHRO, PIRANHAS, WATER POLO, HOCKEY) are ignored entirely; SFUSD classes become closure entries.

## User Directives
