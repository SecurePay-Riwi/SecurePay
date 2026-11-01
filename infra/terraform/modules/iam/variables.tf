variable "name_prefix" {
  description = "Prefix for every resource name, for example securepay-dev."
  type        = string
}

variable "environment" {
  description = "Environment name (dev, prod); part of the parameter paths."
  type        = string
}

variable "github_repository" {
  description = "Repository whose main branch may assume the deploy role."
  type        = string
  default     = "SecurePay-Riwi/SecurePay"
}

variable "create_github_oidc_provider" {
  description = "Create the GitHub OIDC provider. Set false if the account already has one (there can only be one per account)."
  type        = bool
  default     = true
}

variable "engine_reads_database" {
  description = "Temporary: let the engine task read the DATABASE_URL parameter while the engine still reads PostgreSQL. False in prod by design."
  type        = bool
  default     = false
}
