variable "name_prefix" {
  type = string
}

variable "enabled" {
  description = "Create the API: true once the Lambdas exist (lambda_image_tag is set)."
  type        = bool
}

variable "rules_function" {
  description = "Name and ARN of the rules API Lambda (null until it exists)."
  type        = object({ name = string, arn = string })
  default     = null
}

variable "cases_function" {
  description = "Name and ARN of the cases API Lambda (null until it exists)."
  type        = object({ name = string, arn = string })
  default     = null
}

variable "throttle_rate" {
  description = "Requests per second the API accepts on each route (steady)."
  type        = number
  default     = 20
}

variable "throttle_burst" {
  description = "Requests the API accepts at once on each route."
  type        = number
  default     = 40
}

variable "mfa" {
  description = "Cognito MFA: OFF, OPTIONAL or ON. The design says ON for prod; dev keeps OFF so the demo signs in from the CLI."
  type        = string
  default     = "OFF"
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "users" {
  description = "Cognito users to create, e-mail => group (analista or gerente). Each gets a generated permanent password (output user_passwords). Dev only: the passwords are in the state."
  type        = map(string)
  default     = {}

  validation {
    condition     = alltrue([for group in values(var.users) : contains(["analista", "gerente"], group)])
    error_message = "Each user's group must be analista or gerente."
  }
}
