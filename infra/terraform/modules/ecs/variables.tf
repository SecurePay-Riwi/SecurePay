variable "name_prefix" {
  description = "Prefix for every resource name, for example securepay-dev. Also the cluster name."
  type        = string
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  description = "The two public subnets, for the load balancer."
  type        = list(string)
}

variable "app_subnet_ids" {
  description = "The two private application subnets, for the tasks."
  type        = list(string)
}

variable "alb_security_group_id" {
  type = string
}

variable "engine_security_group_id" {
  type = string
}

variable "admin_security_group_id" {
  type = string
}

variable "domain_name" {
  description = "Domain for the load balancer certificate (for example api.example.com). Null: a self-signed certificate."
  type        = string
  default     = null
}

variable "container_insights" {
  description = "CloudWatch Container Insights; extra metrics are billed, so off in dev."
  type        = bool
  default     = true
}

variable "log_retention_days" {
  type    = number
  default = 30
}

# Engine

variable "engine_repository_url" {
  type = string
}

variable "engine_image_tag" {
  description = "Image tag to run (the short git commit). Null: the service is not created yet."
  type        = string
  default     = null

  validation {
    condition     = var.engine_image_tag != "latest"
    error_message = "Use the commit tag, never latest."
  }
}

variable "engine_port" {
  type = number
}

variable "engine_cpu" {
  description = "CPU units per task (512 = 0.5 vCPU)."
  type        = number
  default     = 512
}

variable "engine_memory" {
  description = "Memory per task in MiB."
  type        = number
  default     = 1024
}

variable "engine_min_tasks" {
  description = "At least one task per zone."
  type        = number
  default     = 4

  validation {
    condition     = var.engine_min_tasks >= 2
    error_message = "At least 2 tasks, one per availability zone."
  }
}

variable "engine_max_tasks" {
  type    = number
  default = 24
}

variable "engine_cpu_target" {
  description = "Average CPU percentage the service scales to keep."
  type        = number
  default     = 60
}

variable "engine_execution_role_arn" {
  type = string
}

variable "engine_task_role_arn" {
  type = string
}

variable "engine_environment" {
  description = "Plain environment variables of the engine."
  type        = map(string)
  default     = {}
}

variable "engine_secrets" {
  description = "Environment variables read from Parameter Store: name => parameter ARN."
  type        = map(string)
  default     = {}
}

# Admin task

variable "admin_repository_url" {
  type = string
}

variable "admin_image_tag" {
  description = "Tag of the securepay-seed image. Null: the task definition is not created yet."
  type        = string
  default     = null

  validation {
    condition     = var.admin_image_tag != "latest"
    error_message = "Use the commit tag, never latest."
  }
}

variable "admin_execution_role_arn" {
  type = string
}

variable "admin_task_role_arn" {
  type = string
}

variable "admin_environment" {
  type    = map(string)
  default = {}
}

variable "admin_secrets" {
  description = "name => parameter ARN."
  type        = map(string)
  default     = {}
}
