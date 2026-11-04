variable "name_prefix" {
  description = "Prefix for every resource name, for example securepay-dev."
  type        = string
}

variable "enabled" {
  description = "Create the reconciliation. Needs the statement-reader, difference-writer and alerts Lambdas (lambda_image_tag)."
  type        = bool
}

variable "statement_reader_arn" {
  description = "Lambda of step 1 (services.reconciliation.ingest.handler)."
  type        = string
}

variable "difference_writer_arn" {
  description = "Lambda of step 3 (services.reconciliation.store.handler)."
  type        = string
}

variable "alerts_function_arn" {
  description = "The alerts Lambda; the 06:30 schedule invokes it with {\"job\": \"reconciliation_check\"}."
  type        = string
}

variable "state_machine_role_arn" {
  type = string
}

variable "glue_job_role_arn" {
  description = "Role the Spark job runs with (modules/iam glue-jobs)."
  type        = string
}

variable "scheduler_role_arn" {
  type = string
}

variable "datalake_bucket" {
  type = string
}

variable "artifacts_bucket" {
  description = "Bucket of the Spark job code (jobs/reconciliation/)."
  type        = string
}

variable "business_alerts_topic_arn" {
  type = string
}

variable "ops_alarms_topic_arn" {
  type = string
}

variable "repo_root" {
  description = "Root of the SecurePay repository: the job's code is zipped from services/reconciliation and shared, and its entry point is infra/spark/match_job.py."
  type        = string
}

variable "glue_version" {
  description = "AWS Glue 6.0 is Spark 4.1.1 with Python 3.13 (the pyspark pin of pyproject.toml)."
  type        = string
  default     = "6.0"
}

variable "python_modules" {
  description = "What our code imports that Glue does not bring (it brings boto3), at the versions of uv.lock. test_glue_job.py checks they match."
  type        = string
  default     = "sqlalchemy==2.1.4,python-dotenv==1.2.4"
}

variable "worker_type" {
  description = "G.1X = 1 DPU (4 vCPU, 16 GB) per worker."
  type        = string
  default     = "G.1X"
}

variable "workers" {
  description = "Glue's minimum is 2 (a driver and an executor): a day of a few thousand records does not need more."
  type        = number
  default     = 2
}

variable "job_timeout_minutes" {
  description = "Glue stops a run that takes longer (the machine has its own 4 h 30 min limit)."
  type        = number
  default     = 60
}

variable "timeout_seconds" {
  description = "The machine stops after this: 16200 s = 4 h 30 min, so a 02:00 run still going at 06:30 fails (deadline 07:00)."
  type        = number
  default     = 16200
}

variable "schedule" {
  description = "When the reconciliation of yesterday starts (UTC)."
  type        = string
  default     = "cron(0 7 * * ? *)"
}

variable "check_schedule" {
  description = "When the alerts Lambda checks that yesterday's run is DONE (UTC)."
  type        = string
  default     = "cron(30 11 * * ? *)"
}

# The analytics steps after the store (HU-66, modules/analytics).

variable "analytics_export_arn" {
  description = "ARN of the Lambda analytics-export (services/analytics/export.handler)."
  type        = string
}

variable "analytics_job_name" {
  description = "Name of the analytics Glue job (modules/analytics)."
  type        = string
}

variable "athena_workgroup" {
  description = "Athena workgroup where the views are created (securepay-<env>-powerbi)."
  type        = string
}

variable "glue_database" {
  description = "Glue catalog database of the analytics model."
  type        = string
}

variable "view_queries" {
  description = "CREATE OR REPLACE VIEW of each view (modules/analytics output view_queries)."
  type        = list(string)
}
