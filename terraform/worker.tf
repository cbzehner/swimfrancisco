resource "cloudflare_workers_kv_namespace" "conditions" {
  account_id = var.cloudflare_account_id
  title      = "swimfrancisco-conditions"
}

resource "cloudflare_workers_kv_namespace" "conditions_preview" {
  account_id = var.cloudflare_account_id
  title      = "swimfrancisco-conditions-preview"
}

# Binds the apex swimfrancisco.com to the Worker named var.worker_name.
# The Worker must already exist (created by the first Workers Builds deploy)
# before this applies successfully. Use a two-phase apply: create KV + DNS +
# redirect first, then deploy the Worker via Workers Builds, then apply again
# to attach the custom domain. See docs/deploy.md for the runbook.
#
# `environment` is still accepted by provider v5 but marked deprecated for
# scripts without environments (cloudflare/terraform-provider-cloudflare#5618).
# Keep explicit for now; remove when the provider clarifies the default.
resource "cloudflare_workers_custom_domain" "apex" {
  account_id  = var.cloudflare_account_id
  zone_id     = var.cloudflare_zone_id
  hostname    = var.domain
  service     = var.worker_name
  environment = "production"
}
