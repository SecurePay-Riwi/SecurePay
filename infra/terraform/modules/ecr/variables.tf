variable "name_prefix" {
  description = "Prefix for every resource name, for example securepay-dev."
  type        = string
}

variable "repositories" {
  description = "One repository per image. The names match the deploy role and the task execution roles (modules/iam)."
  type        = list(string)
  default     = ["engine", "generator", "admin"]
}

variable "keep_images" {
  description = "Images kept per repository; older ones are expired."
  type        = number
  default     = 10
}

variable "force_delete" {
  description = "Delete the repository even if it still has images. True only in dev."
  type        = bool
  default     = false
}

variable "lambda_repositories" {
  description = "Repositories whose images Lambda functions of this environment may pull (securepay-<env>-* functions only)."
  type        = list(string)
  default     = []
}

variable "emr_repositories" {
  description = "Repositories whose images EMR Serverless applications of this account may run (custom images)."
  type        = list(string)
  default     = []
}
