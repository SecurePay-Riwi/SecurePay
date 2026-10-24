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
