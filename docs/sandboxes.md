# Disposable project sandboxes

The pilot uses standalone Docker Sandboxes (`sbx`), which runs a private
Linux microVM on Apple silicon. Docker Desktop and a host Docker Engine
are not required. Each workspace owns its checkout, Nix store, processes,
and browser profile. Removing it discards that state; source changes are
exported first.

## Host setup

Install [standalone sbx](https://docs.docker.com/ai/sandboxes/install/) and
run `sbx login`. For hosts with Nix-managed Homebrew taps, Docker also
publishes a macOS tar archive. Keep its `bin` and `libexec` directories
together and put `bin/sbx` on PATH.

The initial trial uses sbx 0.42.1. Initialize its network policy once with
`sbx policy init balanced`. The kit adds the package registries and public
data APIs needed by this project. Browser access to other sites may need
a per-sandbox network rule. SSH agent forwarding is unnecessary for this
workflow and can be disabled through sbx settings.

Wrangler must be authenticated on the host. Check with:

```sh
devenv shell -- ./node_modules/.bin/wrangler whoami
```

## Create and use a workspace

From the repository root:

```sh
just sandbox swimfrancisco codex
just sandbox-attach swimfrancisco
```

Use another name to create an independent workspace. The agent argument
also accepts `claude` and `shell`. A cold launch downloads the tools and
may compile Terraform from source; allow at least ten minutes.

On the pilot host, the prepared Codex template reuses the installed Nix
tools and browsers:

```sh
just sandbox swimfrancisco codex swimfrancisco-dev:20260908
```

This local template was prepared before user work or website logins, with
the checkout, browser profile, and agent session files removed. New
workspaces import current source and receive their own sbx credentials.
Use the default template for Claude. Templates are local to this host;
list them with `sbx template ls`.
The pilot created a fresh workspace from this template in 61 seconds.
Preparing the template itself is a separate, slow operation for this
Nix toolchain; its runnable shell closures were kept while unused build
inputs were garbage-collected before the snapshot.

The launcher copies Git history, current tracked changes, and non-ignored
untracked files into the guest. It does not mount your checkout, home
directory, host Nix daemon, or shared agent skills. Ignored files such as
`.env`, `node_modules`, and Terraform state are not copied. New agent
configuration is supplied by sbx and the project kit.

Inside the guest:

```sh
devenv shell
just dev
```

For a command from a second host terminal:

```sh
just sandbox-exec swimfrancisco devenv shell -- just check
sbx ports swimfrancisco
```

Keep the agent or a foreground command attached while using the browser.
sbx stops the VM about 30 seconds after its last CLI session disconnects,
even when guest background processes exist. To keep the app running from
another host terminal, use `just sandbox-exec swimfrancisco devenv up`.
Run `sbx ports swimfrancisco` again after a restart: host ports can change.

The published `app` port forwards to the local Worker on guest port 8787.
Use `http://localhost:8787` in the shared guest browser for the full site;
Zola's development asset URLs use that origin. The forwarded host port is
also useful for calling the Worker's API directly.
The `browser` port serves noVNC: open its URL with
`/vnc.html?autoconnect=1&resize=scale` appended. Both ports are published
on host loopback. The agent and user share the Chromium session shown
there. The browser's debugging port 9222 stays inside the guest.

Agents can use the project's `playwright-core` package inside devenv with
`chromium.connectOverCDP('http://127.0.0.1:9222')`. Playwright 1.61.1 is
required for the Ubuntu 26.04 ARM browser builds used by the base image.
The image bootstraps Nix, devenv, and display services. Project tools and
libraries come from `devenv.nix`, `devenv.lock`, `package-lock.json`, and
the Python lockfile. Setup pins the browser's Node package from that
environment, so browser startup can run alongside other devenv commands.
Browser binaries and system libraries are installed
by the project's locked Playwright CLI during source setup.
The kit supplies Ubuntu's GSettings schema path and disables Playwright's
preflight library check because Nix's `ldd` misidentifies Ubuntu libraries.
The browser suite verifies both engines actually run. The visible browser
uses Chromium's process sandbox and trusts sbx's proxy CA through Chromium's
NSS database; TLS verification stays enabled.

## Credentials and login prompts

Cloudflare requests use the host's existing Wrangler authentication.
`sandbox/sbxenv.yaml` registers the host project's devenv-managed
`wrangler auth token` as a dynamic secret
source at this sandbox's scope. sbx stores that source in macOS Keychain,
refreshes its resolved value every ten minutes, and injects it only into
requests to `api.cloudflare.com`. `CLOUDFLARE_API_TOKEN` inside the guest is
a placeholder. The host Wrangler login remains in its existing storage;
this setup does not migrate or copy that login file.

The credential retains the host login's permissions. The account ID in
the environment selects the Swimfrancisco account; it is not a security
boundary limiting access to this Worker. Use a separately scoped API token
if that restriction is needed. No deployment or Terraform apply is part
of sandbox setup. R2's S3 credentials for Terraform state are not forwarded
by this Cloudflare HTTP API integration.

To supply a dedicated Cloudflare token, run this on the host and enter it
at the terminal's secret prompt:

```sh
sbx secret set swimfrancisco-cloudflare --sandbox swimfrancisco
```

This replaces the running sandbox's dynamic source with a Keychain-stored
token. Creating a new environment applies the configured source again.
Use sbx's supported agent login flow for Codex or Claude; host agent home
directories are not mounted.

For website passwords or MFA, the agent pauses and asks you to take over
the browser. Enter credentials directly in that browser, then tell the
agent to continue. Passwords do not need to pass through chat. The browser
profile remains private to this workspace and is deleted with it. An
authenticated browser still grants account access to processes in that
workspace, so give it only the sessions needed for the task.

## Export and remove

After the agent finishes:

```sh
just sandbox-export swimfrancisco
just sandbox-remove swimfrancisco
```

Exports under `.sandbox/exports/` contain a cumulative `changes.patch`
against the original host HEAD, a Git bundle preserving guest commits,
and the base commit ID. The patch includes guest commits, tracked edits,
deletions, and non-ignored new files without changing the guest index.
Review the patch and use `git apply --check` before applying it to a host
checkout that may have changed since creation.

Removal stops the sandbox, exports again, then deletes the guest and its
scoped credentials. It keeps exports on the host. If creation fails before
source import, clean up its provisioned credentials with:

```sh
sbx env rm sandbox/sbxenv.yaml --env-arg name=swimfrancisco
```

The `seed` action in `scripts/sandbox.py` can finish source import into a
new empty guest after manual provisioning. It refuses a guest that already
has a Git checkout.

## Validate sandbox changes

For changes to the launcher, kit, development environment, or dependency
setup, create a fresh sandbox from the current checkout using an unused
name. Existing guests do not automatically receive host edits. Use a local
template only when its cached tools are appropriate for the change; test
the default template when changing bootstrap or installation steps.

```sh
just sandbox swim-validation codex
just sandbox-exec swim-validation devenv shell -- just check
just sandbox-exec swim-validation devenv up
```

Keep the last command attached and use another host terminal for inspection.
Verify the complete workflow:

- Open the shared browser using `sbx ports swim-validation`; check the site
  at guest `http://localhost:8787`, live conditions, HTTPS, and keyboard
  takeover with harmless input. Leave real password and MFA entry to the user.
- Confirm the guest has no host directory or SSH-agent mounts, no copied
  ignored `.env`, and only a placeholder Cloudflare token. Exercise a
  read-only Cloudflare API request without logging credentials.
- Stop the test instance with `sbx stop swim-validation`, then run
  `just sandbox-exec swim-validation devenv up` again. Check browser startup
  while running a second devenv command; rediscover the forwarded ports.
- Make disposable guest changes covering a commit, deletion, and new file.
  Run `just sandbox-export swim-validation`; verify the bundle and that
  `changes.patch` applies to its recorded base in a temporary checkout.
  Confirm ignored files are excluded and the guest index is unchanged.
- Run `just sandbox-remove swim-validation`. Confirm the instance and its
  scoped credentials are gone and the host exports remain.

Report which checks ran and any failures or unavailable prerequisites.
Documentation-only changes need link and command verification, without
recreating the sandbox or rerunning the application suite.
