# Repository instructions

Swim Francisco is a Zola site with plain JavaScript, a Cloudflare Worker,
and Python schedule tools. See [README.md](README.md) for layout and commands.

- Keep tools in `devenv.nix` and dependencies in the project lockfiles.
- Spot content lives in `content/spots/`; translations come from `i18n/`.
  Regenerate localized pages instead of editing generated files.
- Use reviewed official sources for schedules. Facility access hours are
  distinct from swim sessions; membership-only spots remain opt-in. See
  [the content schema](docs/spec.md) and [schedule workflow](docs/schedules.md).
- Prefer TOML for authored configuration, JSON for generated data, and
  vendor-required formats where necessary.

## Sandbox and validation

Use the [project sandbox](docs/sandboxes.md) for code execution and testing.
It provides a disposable checkout, devenv, a shared browser, and proxied
Cloudflare access. If already inside it, use that workspace; do not nest
sandboxes. Report unavailable prerequisites rather than claiming validation.

Run focused checks while editing and `devenv shell -- just check` before
delivering code changes. For UI changes, run `devenv up` and inspect
`http://localhost:8787` in the shared guest browser so the Worker is included.
Let the user enter passwords and MFA directly in that browser.

Changes to sandbox setup, devenv, or dependency installation also require
the [fresh-sandbox validation](docs/sandboxes.md#validate-sandbox-changes),
including restart, access controls, export, and removal. Documentation-only
changes need link and command checks. Report what actually ran.

Export guest changes before removal. Deployment follows
[docs/deploy.md](docs/deploy.md) when included in the user's request.
