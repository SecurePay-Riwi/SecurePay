variable "name_prefix" {
  description = "Prefix for every resource name, for example securepay-dev."
  type        = string
}

variable "vpc_id" {
  description = "VPC the groups belong to."
  type        = string
}

variable "engine_port" {
  description = "Port the decision engine listens on behind the load balancer."
  type        = number
}

variable "engine_reads_database" {
  description = "Temporary: open 5432 from sg-engine to sg-rds while the engine still reads PostgreSQL. False in prod by design."
  type        = bool
  default     = false
}
