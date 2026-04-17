{ pkgs, lib, config, inputs, ... }:

{
  packages = [
    pkgs.git
    pkgs.zola
    pkgs.watchexec
  ];

  languages.python.enable = true;
  languages.python.uv.enable = true;

  languages.javascript.enable = true;
  languages.javascript.npm.enable = true;

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

  processes.zola.exec = ''
    watchexec --no-vcs-ignore \
      --watch content --watch templates --watch sass --watch static --watch config.toml \
      -- zola build --base-url http://localhost:8787
  '';
  processes.worker.exec = "npm --prefix worker run dev";
}
