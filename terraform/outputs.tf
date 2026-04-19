output "kv_namespace_id" {
  description = "Paste into worker/wrangler.toml [[kv_namespaces]] id."
  value       = cloudflare_workers_kv_namespace.conditions.id
}

output "kv_preview_namespace_id" {
  description = "Paste into worker/wrangler.toml [[kv_namespaces]] preview_id."
  value       = cloudflare_workers_kv_namespace.conditions_preview.id
}
