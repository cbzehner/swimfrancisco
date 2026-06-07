set positional-arguments

default:
    @just --list

build:
    node scripts/generate-i18n.mjs generate
    node scripts/generate-bulletin.mjs
    zola build

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

test: test-i18n test-python test-js typecheck-worker

check: test build

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
