variable "name_prefix" {
  description = "Prefix for every resource name, for example securepay-dev. Each Lambda is named like its role in modules/iam."
  type        = string
}

variable "repository_url" {
  description = "ECR repository of the product image (the engine's): the same image runs every handler with another command."
  type        = string
}

variable "image_tag" {
  description = "Image tag (short git commit). Unset: no Lambda is created yet, as with the engine service."
  type        = string
  default     = null
}

variable "role_arns" {
  description = "Role ARN by component (modules/iam output role_arns)."
  type        = map(string)
}

variable "app_subnet_ids" {
  description = "Private subnets of the Lambdas that reach RDS."
  type        = list(string)
}

variable "lambda_security_group_id" {
  description = "sg-lambda: reaches RDS on 5432 and AWS services on 443."
  type        = string
}

variable "queue_arns" {
  description = "Queue ARN by consumer (cases, history, analytics)."
  type        = map(string)
}

variable "database_url" {
  description = "DATABASE_URL of the cases, history, alerts and difference-writer Lambdas. Temporary: the master user in dev (security.mdx, Encryption and secrets)."
  type        = string
  sensitive   = true
}

variable "business_alerts_topic_arn" {
  type = string
}

variable "ops_alarms_topic_arn" {
  type = string
}

variable "datalake_bucket" {
  type = string
}

variable "evidence_bucket" {
  type = string
}

variable "evidence_retention_days" {
  description = "Object Lock days of each evidence object. Decimal: 0.0035 (5 minutes) in dev, never 3650 outside prod."
  type        = string
  default     = "0.0035"
}

variable "case_due_minutes" {
  description = "Minutes a case has before it is escalated (RN-09: 240). The cases consumer sets due_at, so a test with 2 shows an escalation in minutes."
  type        = number
  default     = 240
}

variable "alerts_schedule" {
  description = "How often the alerts task runs (EventBridge Scheduler expression)."
  type        = string
  default     = "rate(5 minutes)"
}

variable "consumer_max_concurrency" {
  description = "At most this many copies of the cases and history consumers at once, so they never use up the db.t3.micro connections (2 to 1000)."
  type        = number
  default     = 5
}

variable "memory_mb" {
  description = "Memory of every Lambda (logbook 3.11: 512 MB)."
  type        = number
  default     = 512
}

variable "timeout_seconds" {
  description = "Timeout of every Lambda here. The queues' visibility timeout must be at least this."
  type        = number
  default     = 60
}

variable "log_level" {
  description = "Application log level in CloudWatch (JSON logs)."
  type        = string
  default     = "INFO"
}

variable "log_retention_days" {
  type    = number
  default = 7
}
