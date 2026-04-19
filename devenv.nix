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
}
