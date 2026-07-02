set positional-arguments

default:
    @just --list

build:
    node scripts/generate-i18n.mjs generate
    node scripts/generate-bulletin.mjs
    node scripts/generate-agent-data.mjs
    zola build
    node scripts/generate-build-metadata.mjs

release:
    node scripts/generate-i18n.mjs generate
    node scripts/generate-bulletin.mjs
    just check

sync:
    uv --project schedule-tools sync

dev:
    devenv up

serve:
    node scripts/generate-i18n.mjs generate
    node scripts/generate-bulletin.mjs
    zola serve --interface 127.0.0.1 --port 1111

test-python:
    uv --project schedule-tools run pytest tests

test-js:
    node --test tests/js/*.test.mjs

typecheck-worker:
    npm --prefix worker run typecheck

test-i18n:
    node scripts/generate-i18n.mjs check

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
