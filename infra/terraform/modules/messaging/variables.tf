variable "name_prefix" {
  description = "Prefix for every resource name, for example securepay-dev."
  type        = string
}

variable "queues" {
  description = "Queues subscribed to the decisions topic, one per consumer. The names match the roles in modules/iam (securepay-<env>-<queue>)."
  type        = list(string)
  default     = ["cases", "history", "analytics"]
}

variable "visibility_timeout_seconds" {
  description = "How long a message read by a consumer stays hidden. AWS asks for at least the Lambda timeout and recommends 6 times it (60 s x 6)."
  type        = number
  default     = 360
}

variable "max_receive_count" {
  description = "Attempts before a message moves to its DLQ."
  type        = number
  default     = 5
}

variable "dlq_retention_seconds" {
  description = "How long the DLQs keep a message: 14 days, the SQS maximum, so nothing is deleted before someone looks at it."
  type        = number
  default     = 1209600
}

variable "supervisor_emails" {
  description = "Receive the case escalations (audience = supervisor). Each one confirms the subscription from the e-mail AWS sends."
  type        = list(string)
  default     = []
}

variable "compliance_emails" {
  description = "Receive the restricted list summaries (audience = compliance)."
  type        = list(string)
  default     = []
}

variable "alarm_emails" {
  description = "Receive the operational alarms (messages in a DLQ, failing alerts task)."
  type        = list(string)
  default     = []
}
