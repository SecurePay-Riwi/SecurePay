# What the deployment of the engine and the data stores will need.

output "vpc_id" {
  value = module.network.vpc_id
}

output "public_subnet_ids" {
  value = module.network.public_subnet_ids
}

output "app_subnet_ids" {
  value = module.network.app_subnet_ids
}

output "data_subnet_ids" {
  value = module.network.data_subnet_ids
}

output "nat_public_ips" {
  value = module.network.nat_public_ips
}

output "security_group_ids" {
  value = module.security_groups.ids
}

output "role_arns" {
  value = module.iam.role_arns
}

output "bucket_names" {
  value = module.storage.bucket_names
}

output "database_endpoint" {
  value = module.database.endpoint
}

output "database_master_password_parameter" {
  value = module.database.master_password_parameter
}

output "ecr_repository_urls" {
  description = "Where to push each image: <url>:<short commit>."
  value       = module.ecr.repository_urls
}

output "alb_dns_name" {
  description = "Public name of the load balancer: curl -k https://<this>/health"
  value       = module.ecs.alb_dns_name
}

output "ecs_cluster_name" {
  value = module.ecs.cluster_name
}

output "cache_address" {
  value = module.cache.address
}

output "admin_run_task_command" {
  description = "Seeds the database (once admin_image_tag is set)."
  value       = module.ecs.admin_run_task_command
}

output "certificate_validation_records" {
  description = "With domain_name: the DNS record to add at the DNS provider."
  value       = module.ecs.certificate_validation_records
}
