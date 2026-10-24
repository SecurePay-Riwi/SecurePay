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
