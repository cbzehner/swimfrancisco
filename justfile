set positional-arguments

default:
    @just --list

# Disposable Linux workspace, browser, and host-proxied Cloudflare access.
sandbox name="swimfrancisco" agent="codex" template="":
    python3 scripts/sandbox.py create "$1" --agent "$2" --template "$3"

sandbox-attach name="swimfrancisco":
    python3 scripts/sandbox.py attach "$1"

sandbox-exec name="swimfrancisco" *command:
    sandbox_name="$1"; shift; python3 scripts/sandbox.py exec "$sandbox_name" -- "$@"

# Host Keychain -> sandbox proxy; profile is jev, extraction, or cloudflare.
sandbox-grant name profile:
    python3 scripts/sandbox.py grant "$1" --profile "$2"

# R2 signing requires real credentials, sent only to this Terraform process.
sandbox-terraform name +args:
    sandbox_name="$1"; shift; SECRETSPEC_REASON="Run Swim Francisco Terraform" secretspec run --provider keyring --profile infrastructure -- python3 scripts/sandbox.py terraform "$sandbox_name" -- "$@"

sandbox-export name="swimfrancisco":
    python3 scripts/sandbox.py export "$1"

# Export first; then delete the guest and its scoped credentials.
sandbox-remove name="swimfrancisco":
    python3 scripts/sandbox.py remove "$1"

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

# The site, the worker, and every schedule are Pacific; pinning TZ keeps a
# test that reads the local clock from passing only on a Pacific machine.
test-python:
    TZ=America/Los_Angeles uv --project schedule-tools run pytest tests

test-js:
    TZ=America/Los_Angeles node --test tests/js/*.test.mjs

typecheck-worker:
    npm --prefix worker run typecheck

test-i18n:
    npm run check-i18n

# Real-browser integration tests (WebKit + Chromium). Builds the site on an
# ephemeral port and drives the regressions that node:test can't see.
# One-time setup per machine: `just browsers`.
test-browser:
    TZ=America/Los_Angeles node --test tests/browser/*.test.mjs

test-e2e:
    npm run test:e2e

browsers:
    node node_modules/playwright-core/cli.js install webkit chromium
    ./node_modules/.bin/e2e-web install webkit chromium

test: test-i18n test-python test-js typecheck-worker

check: test test-browser test-e2e build

smoke-production *args:
    node scripts/smoke-production.mjs {{args}}

refresh-conditions:
    curl -fsS "http://localhost:8787/__scheduled" && echo
    @echo "cron handler invoked; fetch with: curl -s http://localhost:8787/api/conditions | jq"

schedules *args:
    uv --project schedule-tools run schedules "$@"

schedules-extract *args:
    uv --project schedule-tools run schedules extract "$@"

schedules-review *args:
    uv --project schedule-tools run schedules review "$@"

schedules-eval *args:
    uv --project schedule-tools run schedules eval "$@"
