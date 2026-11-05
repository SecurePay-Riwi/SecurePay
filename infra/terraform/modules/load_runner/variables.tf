variable "name_prefix" {
  type = string
}

variable "enabled" {
  description = "Create the machine. It costs while it runs: create it for the load test only."
  type        = bool
}

variable "vpc_id" {
  type = string
}

variable "subnet_id" {
  description = "An application subnet: no public address, out through the NAT Gateway."
  type        = string
}

variable "target_host" {
  description = "Host the load test calls (the load balancer's DNS name)."
  type        = string
}

variable "results_bucket" {
  description = "Bucket where each run leaves its Locust CSV files, under load-tests/."
  type        = string
}

variable "instance_type" {
  description = "Two vCPU, on AWS's free account plan. Locust with one process per vCPU sends 300 tx/s with room to spare."
  type        = string
  default     = "c7i-flex.large"
}

variable "repository" {
  description = "Git repository with infra/load (public, cloned without credentials)."
  type        = string
  default     = "https://github.com/SecurePay-Riwi/SecurePay.git"
}

variable "git_ref" {
  description = "Branch or tag of the repository to run."
  type        = string
  default     = "main"
}
