output "address" {
  description = "Host name of the cache (inside the VPC only)."
  value       = local.endpoint.address
}

output "port" {
  value = local.endpoint.port
}

output "url" {
  description = "Connection URL for the services, with TLS."
  value       = "rediss://${local.endpoint.address}:${local.endpoint.port}"
}
