set positional-arguments

default:
    @just --list

# Same pipeline Cloudflare Workers Builds runs; package.json is the one
# definition of the build steps.
build:
    npm run build

# Refresh committed generated artifacts (localized pages, bulletin) before
# the full gate, so `test-i18n` checks the regenerated tree.
release:
    npm run generate-i18n
    npm run generate-bulletin
    just check

sync:
    uv --project schedule-tools sync

dev:
    devenv up

serve:
    npm run generate-i18n
    npm run generate-bulletin
    npm run generate-agent-data
    zola serve --interface 127.0.0.1 --port 1111

test-python:
    uv --project schedule-tools run pytest tests

test-js:
    node --test tests/js/*.test.mjs

typecheck-worker:
    npm --prefix worker run typecheck

test-i18n:
    npm run check-i18n

# Real-browser integration tests (WebKit + Chromium). Builds the site on an
# ephemeral port and drives the regressions that node:test can't see.
# One-time setup per machine: `just browsers`.
test-browser:
    node --test tests/browser/*.test.mjs

browsers:
    node node_modules/playwright-core/cli.js install webkit chromium

test: test-i18n test-python test-js typecheck-worker

check: test test-browser build

smoke-production *args:
    node scripts/smoke-production.mjs {{args}}

refresh-conditions:
    curl -fsS "http://localhost:8787/__scheduled" && echo
    @echo "cron handler invoked; fetch with: curl -s http://localhost:8787/api/conditions | jq"

schedules *args:
    set -a; [ ! -f .env ] || . ./.env; set +a; uv --project schedule-tools run schedules "$@"

schedules-extract *args:
    set -a; [ ! -f .env ] || . ./.env; set +a; uv --project schedule-tools run schedules extract "$@"

schedules-review *args:
    set -a; [ ! -f .env ] || . ./.env; set +a; uv --project schedule-tools run schedules review "$@"

schedules-eval *args:
    uv --project schedule-tools run schedules eval "$@"
