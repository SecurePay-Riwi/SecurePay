variable "name_prefix" {
  description = "Prefix for every resource name, for example securepay-dev."
  type        = string
}

variable "environment" {
  description = "Environment name; part of the parameter paths (/securepay/<env>/rds/...)."
  type        = string
}

variable "data_subnet_ids" {
  description = "The two private data subnets."
  type        = list(string)
}

variable "security_group_id" {
  description = "sg-rds: 5432 only from sg-lambda and sg-admin."
  type        = string
}

variable "instance_class" {
  type    = string
  default = "db.t3.micro"
}

variable "multi_az" {
  description = "Standby in the second zone with automatic failover."
  type        = bool
  default     = true
}

variable "allocated_storage_gb" {
  type    = number
  default = 20
}

variable "backup_retention_days" {
  type    = number
  default = 7
}

variable "disposable" {
  description = "Dev only: no deletion protection and no final snapshot, so terraform destroy removes it at once."
  type        = bool
  default     = false
}

variable "component_users" {
  description = "Database users with their own password in Parameter Store (security.mdx, Encryption and secrets)."
  type        = list(string)
  default     = ["cases_consumer", "rules_api", "cases_api", "rules_reader", "alerts", "reconciliation"]
}
