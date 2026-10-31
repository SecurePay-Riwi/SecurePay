# One group per function; rules point at other groups, not at address
# ranges (doc-website/docs/architecture/security.mdx#security-groups).
# Terraform removes the default allow-all egress rule, so a group with no
# egress rule below has no outbound access.

locals {
  groups = {
    alb    = "Load balancer: HTTPS from the internet to the engine"
    engine = "Decision engine (Fargate)"
    lambda = "Lambdas inside the VPC"
    admin  = "Admin task: migrations and seed"
    rds    = "RDS PostgreSQL"
    cache  = "ElastiCache Serverless for Valkey"
  }

  # Group-to-group rules: one ingress rule in "to" and the matching egress
  # rule in "from".
  links = {
    alb_engine     = { from = "alb", to = "engine", port = var.engine_port }
    engine_cache   = { from = "engine", to = "cache", port = 6379 }
    engine_cache_r = { from = "engine", to = "cache", port = 6380 }
    lambda_rds     = { from = "lambda", to = "rds", port = 5432 }
    lambda_cache   = { from = "lambda", to = "cache", port = 6379 }
    lambda_cache_r = { from = "lambda", to = "cache", port = 6380 }
    admin_rds      = { from = "admin", to = "rds", port = 5432 }
  }

  # Temporary (agreed with the team on 2026-10-31): today the engine still
  # reads accounts, merchants, owners and the restricted list from
  # PostgreSQL. Remove it, with engine_reads_database = false, once that data
  # is loaded into the cache (security.mdx, "The engine no longer reaches
  # the database").
  temporary_links = var.engine_reads_database ? {
    engine_rds = { from = "engine", to = "rds", port = 5432 }
  } : {}

  all_links = merge(local.links, local.temporary_links)

  # Outbound HTTPS to AWS services (SNS, ECR, CloudWatch, X-Ray, Parameter
  # Store, DynamoDB through its endpoint) and the list service.
  https_out = ["engine", "lambda", "admin"]
}

resource "aws_security_group" "this" {
  for_each = local.groups

  name        = "${var.name_prefix}-sg-${each.key}"
  description = each.value
  vpc_id      = var.vpc_id

  tags = { Name = "${var.name_prefix}-sg-${each.key}" }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  security_group_id = aws_security_group.this["alb"].id
  description       = "HTTPS from the internet"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "link" {
  for_each = local.all_links

  security_group_id            = aws_security_group.this[each.value.to].id
  referenced_security_group_id = aws_security_group.this[each.value.from].id
  description                  = "${each.value.port}/TCP from sg-${each.value.from}"
  ip_protocol                  = "tcp"
  from_port                    = each.value.port
  to_port                      = each.value.port
}

resource "aws_vpc_security_group_egress_rule" "link" {
  for_each = local.all_links

  security_group_id            = aws_security_group.this[each.value.from].id
  referenced_security_group_id = aws_security_group.this[each.value.to].id
  description                  = "${each.value.port}/TCP to sg-${each.value.to}"
  ip_protocol                  = "tcp"
  from_port                    = each.value.port
  to_port                      = each.value.port
}

resource "aws_vpc_security_group_egress_rule" "https" {
  for_each = toset(local.https_out)

  security_group_id = aws_security_group.this[each.key].id
  description       = "HTTPS to AWS services"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}
