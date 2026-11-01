output "address" {
  description = "Host name of the cache (inside the VPC only)."
  value       = aws_elasticache_serverless_cache.this.endpoint[0].address
}

output "port" {
  value = aws_elasticache_serverless_cache.this.endpoint[0].port
}

output "url" {
  description = "Connection URL for the services, with TLS."
  value       = "rediss://${aws_elasticache_serverless_cache.this.endpoint[0].address}:${aws_elasticache_serverless_cache.this.endpoint[0].port}"
}
