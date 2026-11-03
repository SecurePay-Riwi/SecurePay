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

variable "github_immutable_subject" {
  description = "Immutable subject prefix of the repository (owner@id/repo@id), shown by `gh api repos/<owner>/<repo>/actions/oidc/customization/sub` as sub_claim_prefix."
  type        = string
  default     = "repo:SecurePay-Riwi@333775069/SecurePay@1387412508"
}

variable "create_github_oidc_provider" {
  description = "Create the GitHub OIDC provider. Set false if the account already has one (there can only be one per account)."
  type        = bool
  default     = true
}

