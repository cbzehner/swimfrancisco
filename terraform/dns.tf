# The apex A/CNAME is created automatically by Cloudflare when the
# Workers Custom Domain (terraform/worker.tf) attaches the Worker to
# the apex. We only manage the www CNAME explicitly.
resource "cloudflare_dns_record" "www" {
  zone_id = var.cloudflare_zone_id
  name    = "www"
  type    = "CNAME"
  content = var.domain
  ttl     = 1 # 1 = auto (required when proxied)
  proxied = true
}

# Permanent 301 from www.swimfrancisco.com to https://swimfrancisco.com/<path>.
# Implemented as a zone-level dynamic redirect ruleset so the path and query
# are preserved without any Pages/Worker involvement.
resource "cloudflare_ruleset" "www_redirect" {
  zone_id = var.cloudflare_zone_id
  name    = "www to apex redirect"
  kind    = "zone"
  phase   = "http_request_dynamic_redirect"

  rules = [{
    action      = "redirect"
    expression  = "(http.host eq \"www.${var.domain}\")"
    description = "Redirect www to apex"
    action_parameters = {
      from_value = {
        status_code = 301
        target_url = {
          expression = "concat(\"https://${var.domain}\", http.request.uri.path)"
        }
        preserve_query_string = true
      }
    }
  }]
}
