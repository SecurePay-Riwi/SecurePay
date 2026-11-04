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

variable "database" {
  description = <<-EOT
    Where the Lambdas reach RDS (modules/database outputs). No password: each
    Lambda reads its own from <parameter_path>/<user> at startup (MAG-361).
    instance_resource_id and password_versions only make db-bootstrap run
    again when the database is new or a password changes.
  EOT
  type = object({
    host                 = string
    port                 = number
    name                 = string
    master_username      = string
    parameter_path       = string
    instance_resource_id = string
    password_versions    = string
  })
}

variable "cache_url" {
  description = "VALKEY_URL of the cache, for the cache loader (list-loader)."
  type        = string
}

variable "list_loader_schedule" {
  description = "When the cache loader copies the reference data into the cache (UTC; 01:00 Bogota, before the 02:00 reconciliation)."
  type        = string
  default     = "cron(0 6 * * ? *)"
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

variable "analytics_batch_size" {
  description = "Decisions per analytics batch, written as one S3 object (Firehose is not on the free plan). A batch above 10 needs a batching window; Lambda sends fewer when the batch passes 6 MB."
  type        = number
  default     = 1000

  validation {
    condition     = var.analytics_batch_size >= 1 && var.analytics_batch_size <= 10000
    error_message = "A standard SQS queue allows batches of 1 to 10000."
  }
}

variable "analytics_batching_window_seconds" {
  description = "Longest wait to fill an analytics batch. The queues' visibility timeout must cover 6 x timeout_seconds plus this."
  type        = number
  default     = 60
}

variable "memory_mb" {
  description = "Memory of every Lambda (logbook 3.11: 512 MB)."
  type        = number
  default     = 512
}

variable "timeout_seconds" {
  description = "Timeout of every Lambda here. The queues' visibility timeout must be at least this (AWS recommends 6 x this, plus the analytics batching window)."
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

# The exchange-rates Lambda (HU-42) runs securepay-apis' image, not the
# engine's, and that repository deploys it with its own workflow.

variable "apis_repository_url" {
  description = "ECR repository of the securepay-apis image."
  type        = string
}

variable "apis_image_tag" {
  description = "securepay-apis image tag in ECR (the short git commit). Unset: no exchange-rates Lambda yet."
  type        = string
  default     = null
}

variable "exchange_rates_table" {
  description = "DynamoDB table the exchange-rates Lambda writes and the engine reads."
  type        = string
}

variable "exchange_rates_schedule" {
  description = "When the exchange-rates Lambda runs, in UTC. 16:00 UTC is 11:00 Bogota, after Frankfurter publishes the day's rates (around 16:00 Central European Time)."
  type        = string
  default     = "cron(0 16 * * ? *)"
}
