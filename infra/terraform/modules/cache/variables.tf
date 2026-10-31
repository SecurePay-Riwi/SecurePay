variable "name_prefix" {
  description = "Prefix for every resource name, for example securepay-dev."
  type        = string
}

variable "data_subnet_ids" {
  description = "The two private data subnets."
  type        = list(string)
}

variable "security_group_id" {
  description = "sg-cache: 6379 and 6380 only from sg-engine and sg-lambda."
  type        = string
}

variable "major_engine_version" {
  type    = string
  default = "8"
}

variable "max_data_storage_gb" {
  description = "Most data the cache may hold. AWS bills at least 100 MB for Valkey."
  type        = number
  default     = 1
}

variable "max_ecpu_per_second" {
  description = "Most ElastiCache Processing Units per second."
  type        = number
  default     = 5000
}

variable "snapshot_retention_days" {
  description = "Daily snapshots kept. 0 in dev: the cache holds nothing that cannot be rebuilt."
  type        = number
  default     = 1
}
