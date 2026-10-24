variable "name_prefix" {
  description = "Prefix for every resource name, for example securepay-dev."
  type        = string
}

variable "force_destroy" {
  description = "Let terraform destroy delete buckets that still hold objects (true in dev only). Objects under Object Lock retention still block it until the retention ends."
  type        = bool
  default     = false
}

variable "evidence_default_retention_years" {
  description = "Default COMPLIANCE retention of the evidence bucket, in years (10 in prod). 0 = no default retention: each object carries its own retain-until date."
  type        = number
  default     = 10
}
