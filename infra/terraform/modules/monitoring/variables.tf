variable "name_prefix" {
  description = "Prefix for every resource name, for example securepay-dev."
  type        = string
}

variable "ops_alarms_topic_arn" {
  description = "Every alarm e-mails the team through this topic (-ops-alarms)."
  type        = string
}

variable "engine_deployed" {
  description = "The engine service exists (engine_image_tag set): the load balancer alarms and metric filters only make sense then."
  type        = bool
}

variable "alb_arn_suffix" {
  type = string
}

variable "target_group_arn_suffix" {
  type = string
}

variable "availability_zones" {
  description = "Zones of the engine tasks (alarm 7 checks each one)."
  type        = list(string)
}

variable "min_healthy_tasks_per_zone" {
  description = "Alarm 7: fewer healthy engine tasks than this in a zone. The design says 2 (losing a zone must still leave 12 of 24); dev runs 1 per zone."
  type        = number
  default     = 1
}

variable "engine_log_group_name" {
  type = string
}

variable "cluster_name" {
  type = string
}

variable "queues" {
  description = "Names of the consumer queues (cases, history, analytics), for alarm 4 and the dashboard."
  type        = list(string)
}

variable "lambda_function_names" {
  description = "Lambda name by component (modules/lambdas output function_names; empty until lambda_image_tag)."
  type        = map(string)
}

variable "exchange_rates_deployed" {
  description = "Whether the exchange-rates Lambda exists (apis_image_tag is set); known at plan time, unlike its name."
  type        = bool
  default     = false
}

variable "exchange_rates_function_name" {
  description = "The exchange-rates Lambda (null until apis_image_tag)."
  type        = string
  default     = null
}

variable "state_machine_arn" {
  description = "The nightly reconciliation (null until lambda_image_tag)."
  type        = string
  default     = null
}

variable "db_instance_identifier" {
  type = string
}

variable "db_max_connections" {
  description = "max_connections of the instance class: LEAST(memory / 9531392, 5000), about 87 for a db.t3.micro (1 GiB). Alarm 8 fires at 80 %."
  type        = number
  default     = 87
}

variable "latency_p99_seconds" {
  description = "Alarm 1: p99 of the engine's TargetResponseTime. The limit is 200 ms; the alarm fires before it is broken."
  type        = number
  default     = 0.18
}

variable "slow_decision_ms" {
  description = "Decisions at least this slow are logged by the engine (SLOW_DECISION_MS) and listed by the saved query."
  type        = number
  default     = 150
}

variable "exchange_rate_max_age_days" {
  description = "Alarm when the exchange-rates Lambda has not succeeded for this many days (the rates in the table are that old)."
  type        = number
  default     = 4
}
