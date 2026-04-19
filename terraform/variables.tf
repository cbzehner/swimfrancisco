variable "cloudflare_account_id" {
  type        = string
  description = "Cloudflare account that owns the Workers/KV/Pages resources."
  default     = "d985f954e272a26b858d9f8c5fc53217"
}

variable "cloudflare_zone_id" {
  type        = string
  description = "Cloudflare zone for swimfrancisco.com."
  default     = "1daf29ffafa64dbdda65c32727337eb8"
}

variable "domain" {
  type        = string
  description = "Apex domain served by the Worker."
  default     = "swimfrancisco.com"
}

variable "worker_name" {
  type        = string
  description = "Script name of the Worker serving the site. Must match the `name` in worker/wrangler.toml."
  default     = "swimfrancisco"
}
