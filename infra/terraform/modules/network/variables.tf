variable "name_prefix" {
  description = "Prefix for every resource name, for example securepay-dev."
  type        = string
}

variable "vpc_cidr" {
  description = "Address range of the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "The two availability zones, in the order of the subnet ranges below."
  type        = list(string)

  validation {
    condition     = length(var.availability_zones) == 2
    error_message = "The design uses exactly two availability zones."
  }
}

variable "zone_suffixes" {
  description = "Suffix of each zone in the resource names (public-a, app-b...)."
  type        = list(string)
  default     = ["a", "b"]
}

variable "public_subnet_cidrs" {
  description = "Public tier: load balancer and NAT Gateways."
  type        = list(string)
  default     = ["10.0.0.0/24", "10.0.1.0/24"]
}

variable "app_subnet_cidrs" {
  description = "Private application tier: Fargate tasks and the Lambdas that use the database or the cache."
  type        = list(string)
  default     = ["10.0.10.0/24", "10.0.11.0/24"]
}

variable "data_subnet_cidrs" {
  description = "Private data tier: RDS and the cache. No internet egress."
  type        = list(string)
  default     = ["10.0.20.0/24", "10.0.21.0/24"]
}
