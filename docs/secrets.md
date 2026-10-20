# Task credentials

`secretspec.toml` declares the keys; the host macOS Keychain stores their
values through SecretSpec's `keyring` provider. `devenv.nix` supplies the CLI.
There is no default profile. Ordinary development, tests, and builds do not
resolve credentials. Existing `.env` files stay ignored but are no longer
loaded by devenv or the schedule recipes.

## Enter keys on the host

From the repository root, run the commands for the tasks you use. Each command
prompts for the value; do not put values in command arguments or chat.

```sh
secretspec set TYPESAFE_API_KEY --provider keyring --profile jev
secretspec set OPENAI_API_KEY --provider keyring --profile extraction
```

Infrastructure is optional. Store a dedicated Cloudflare API token and the
R2 state bucket's key pair together in its profile:

```sh
secretspec set CLOUDFLARE_API_TOKEN --provider keyring --profile infrastructure
secretspec set AWS_ACCESS_KEY_ID --provider keyring --profile infrastructure
secretspec set AWS_SECRET_ACCESS_KEY --provider keyring --profile infrastructure
```

If SecretSpec asks for an access reason, add `--reason "Configure Swim Francisco credentials"`.
Approve macOS Keychain access directly when prompted. Wrangler OAuth, GitHub,
and coding-agent logins remain managed by their existing tools. GitHub Actions
continues using its existing repository secrets.

Copy existing values from your private `.env` into these prompts yourself.
After validating the relevant task, remove those entries from `.env`. The
setup does not read, migrate, delete, or rotate your existing secret values.
Restart existing shells or reload direnv to discard previously loaded values.

## Grant API access to a sandbox

Create a [project sandbox](sandboxes.md), then grant only the needed service:

```sh
just sandbox-grant swimfrancisco jev
just sandbox-grant swimfrancisco extraction
```

These commands register a host SecretSpec resolver at that sandbox's scope.
The proxy resolves only the selected key, refreshes it every ten minutes,
and replaces the guest placeholder only on requests to `api.typesafe.ai` or
`api.openai.com`, respectively. The real API key is not copied into guest
files or environment variables. Domain access does not limit the key's API
permissions or spend; use a suitably scoped provider key.

Then run the [Jev trial](jev-trial.md) or schedule extraction through
`just sandbox-exec <name> devenv shell -- <command>`, or open a new session
with `just sandbox-attach <name>`. These helpers read only registered placeholder
metadata and pass it to the new guest process. Plain `sbx exec` and already
open shells do not pick up newly granted placeholders. The grant supplies `TYPESAFE_API_KEY` or
`OPENAI_API_KEY` as a proxy placeholder. Paid calls remain explicit.

To replace the sandbox's default host Wrangler login with the dedicated
Cloudflare token from the infrastructure profile:

```sh
just sandbox-grant swimfrancisco cloudflare
```

This resolves only `CLOUDFLARE_API_TOKEN`; R2 keys are not required for this
grant. Creating a new sandbox uses Wrangler authentication again until you
explicitly grant the dedicated token. Removing the sandbox removes its scoped
proxy credentials; the original SecretSpec Keychain entries remain on the host.

## Terraform with R2 signing

R2 uses S3 request signatures, which require the actual key pair. A bearer
header proxy cannot substitute for the signing secret. Use the host command:

```sh
just sandbox-terraform swimfrancisco version
just sandbox-terraform swimfrancisco init
just sandbox-terraform swimfrancisco plan
```

SecretSpec resolves the infrastructure profile on the host. The launcher
passes exactly its three values over stdin to a guest wrapper, which installs
them only in the Terraform process environment. No credential file or secret
command-line argument is created. Other guest processes with sufficient
permissions can inspect that process while it runs; use a trusted disposable
guest for infrastructure work. The wrapper clears inherited model keys and
Terraform trace logging, disables interactive input, and then executes
Terraform in `terraform/`. It grants network access to the pinned state
endpoint and Terraform registries. Apply remains an explicit operator action;
use a reviewed saved plan as described in the Terraform runbook.

## References

- [SecretSpec profiles](https://secretspec.dev/concepts/profiles/)
- [Keyring provider](https://secretspec.dev/providers/keyring/)
- [Sandbox custom secrets](https://docs.docker.com/reference/cli/sbx/secret/set-custom/)
