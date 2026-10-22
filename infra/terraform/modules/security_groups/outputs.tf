output "ids" {
  description = "Group id by function: alb, engine, lambda, admin, rds, cache."
  value       = { for key, group in aws_security_group.this : key => group.id }
}
