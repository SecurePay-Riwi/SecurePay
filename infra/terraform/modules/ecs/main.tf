# The decision engine on ECS Fargate behind the Application Load Balancer
# (infrastructure.mdx, "Compute and ingress"), plus the admin task that
# seeds the database on demand. The names (cluster securepay-<env>, service
# engine, task definition securepay-<env>-admin, log groups /ecs/...) are the
# ones the roles of modules/iam already allow.

data "aws_region" "current" {}

resource "aws_ecs_cluster" "this" {
  name = var.name_prefix

  setting {
    name  = "containerInsights"
    value = var.container_insights ? "enabled" : "disabled"
  }
}

resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name       = aws_ecs_cluster.this.name
  capacity_providers = ["FARGATE"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}

resource "aws_cloudwatch_log_group" "this" {
  for_each = toset(["engine", "admin"])

  name              = "/ecs/${var.name_prefix}-${each.key}"
  retention_in_days = var.log_retention_days
}

locals {
  region = data.aws_region.current.name

  # Environment and secrets in the shape ECS expects.
  engine_environment = [for name, value in var.engine_environment : { name = name, value = value }]
  engine_secrets     = [for name, arn in var.engine_secrets : { name = name, valueFrom = arn }]
  admin_environment  = [for name, value in var.admin_environment : { name = name, value = value }]
  admin_secrets      = [for name, arn in var.admin_secrets : { name = name, valueFrom = arn }]
}
