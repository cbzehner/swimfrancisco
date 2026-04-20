{ pkgs, lib, config, inputs, ... }:

{
  packages = [
    pkgs.git
    pkgs.zola
    pkgs.watchexec
    pkgs.terraform
    # Node ≥22.18 — unflagged TS type stripping for `node --test` against
    # `worker/src/*.ts`. nixpkgs currently ships 22.22+, which clears the bar.
    pkgs.nodejs_22
    # Provides `vscode-json-language-server` for editor-side schema validation
    # of reviewed-snapshot JSON. Helix picks it up automatically when it sees
    # a `$schema` key pointing at `data/reviewed-snapshots/schema.json`.
    pkgs.vscode-langservers-extracted
  ];

  languages.python.enable = true;
  languages.python.uv.enable = true;

  languages.javascript.enable = true;
  languages.javascript.npm.enable = true;
  dotenv.enable = true;
  dotenv.filename = [ ".env" ];

  # `devenv up` starts both: a Zola build-on-change watcher and wrangler dev.
  # Wrangler serves ./public as static assets and handles /api/* via the Worker,
  # matching prod's single-origin shape. Open http://localhost:8787.
  # Manually trigger the Worker's scheduled handler (the hourly cron that
  # fetches NOAA/NDBC and writes KV). Wrangler's `--test-scheduled` flag
  # (set in worker/package.json) exposes this at /__scheduled.
  scripts.refresh-conditions = {
    description = "Trigger the Worker cron handler to refresh conditions in KV";
    exec = ''
      set -euo pipefail
      curl -fsS "http://localhost:8787/__scheduled" && echo
      echo "cron handler invoked — fetch with: curl -s http://localhost:8787/api/conditions | jq"
    '';
  };

  # Pipeline runners. Dry-run first to preview; live run writes to
  # content/spots/ and data/extraction-state.json.
  scripts.schedules-dry-run = {
    description = "Run the schedule extraction pipeline without writing (preview mode)";
    exec = ''
      set -euo pipefail
      uv run schedules extract --dry-run "$@"
    '';
  };
  scripts.schedules-extract = {
    description = "Run the schedule extraction pipeline live (writes content and state)";
    exec = ''
      set -euo pipefail
      uv run schedules extract "$@"
    '';
  };

  processes.zola.exec = ''
    watchexec --no-vcs-ignore \
      --watch content --watch templates --watch sass --watch static --watch config.toml \
      -- zola build --base-url http://localhost:8787
  '';
  # Wrangler dev snapshots `public/` at startup and doesn't hot-reload static
  # assets. Wrap it in a watchexec that restarts the server whenever the Zola
  # watcher rewrites public/, so template/SCSS edits are picked up without a
  # manual `devenv up` restart. Debounce swallows Zola's multi-file write burst.
  processes.worker.exec = ''
    watchexec --no-vcs-ignore --restart --debounce 500ms --watch public \
      -- npm --prefix worker run dev
  '';
  # Seed KV on startup so /api/conditions returns data instead of 503 on a
  # fresh `devenv up`. Polls until wrangler is listening, then fires the
  # cron handler once. Offline-safe (swallows curl failures). Ends with
  # `sleep infinity` because devenv flags exited processes as crashed;
  # idling is cheaper than that noise.
  processes.seed-conditions.exec = ''
    set -u
    echo "seed-conditions: waiting for wrangler on :8787..."
    # Poll for ANY HTTP response. Drop `-f` so curl returns 0 on 503 and
    # writes the code to stdout via `-w`. `-o /dev/null` discards the body.
    until code=$(curl -sS -o /dev/null -w "%{http_code}" http://localhost:8787/api/conditions 2>/dev/null) \
          && [ -n "$code" ] && [ "$code" != "000" ]; do
      sleep 1
    done
    echo "seed-conditions: wrangler up (got $code), firing /__scheduled"
    curl -sS http://localhost:8787/__scheduled > /dev/null 2>&1 \
      && echo "seed-conditions: KV populated" \
      || echo "seed-conditions: skipped (offline or worker error)"
    # Idle so devenv doesn't flag us as crashed.
    sleep infinity
  '';
}
