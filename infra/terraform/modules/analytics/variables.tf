variable "name_prefix" {
  description = "Prefix for every resource name, for example securepay-dev."
  type        = string
}

variable "enabled" {
  description = "Create the Glue job (with the Lambdas: lambda_image_tag). The catalog and the workgroup exist always, so Power BI can be set up first."
  type        = bool
}

variable "glue_job_role_arn" {
  description = "Role glue-jobs of modules/iam."
  type        = string
}

variable "datalake_bucket" {
  type = string
}

variable "artifacts_bucket" {
  type = string
}

variable "code_path" {
  description = "s3:// path of the code zip that modules/reconciliation builds (services/reconciliation, services/analytics and shared): both Spark jobs use it."
  type        = string
}

variable "repo_root" {
  description = "Root of the SecurePay repository, to read infra/spark/analytics_job.py and the view files."
  type        = string
}

variable "glue_version" {
  description = "AWS Glue 6.0 = Spark 4.1.1 and Python 3.13, the versions pyspark is pinned to."
  type        = string
  default     = "6.0"
}

variable "python_modules" {
  description = "What the ETL imports that Glue does not bring (it brings boto3), at the versions of uv.lock: shared/rule_catalog.py needs pydantic, shared/cases.py SQLAlchemy. services/analytics/tests/test_glue_job.py checks they match."
  type        = string
  default     = "sqlalchemy==2.1.4,python-dotenv==1.2.4,pydantic==2.14.1,pydantic-core==2.50.1,annotated-types==0.8.0,typing-inspection==0.4.4,typing-extensions==4.16.0"
}

variable "worker_type" {
  description = "G.1X = 1 DPU (4 vCPU, 16 GB) per worker."
  type        = string
  default     = "G.1X"
}

variable "workers" {
  description = "Glue's minimum for a Spark job is 2."
  type        = number
  default     = 2
}

variable "job_timeout_minutes" {
  type    = number
  default = 60
}

variable "bytes_scanned_cutoff" {
  description = "Most bytes one Athena query may scan before Athena cancels it (cost guard; 1 GB = USD 0.005)."
  type        = number
  default     = 1073741824
}
