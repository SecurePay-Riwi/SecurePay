# ElastiCache for Valkey (infrastructure.mdx, "Data"): in the data subnets,
# reachable only from sg-engine and sg-lambda. Encryption in transit is always
# on, so clients connect with rediss://. Both kinds speak the cluster protocol
# (VALKEY_CLUSTER=true).
#
# Serverless by default. With node_type set it is a node-based cluster
# instead (one shard, a primary and a replica in the other zone): the load
# test of 2026-11-07 (run 7) traced a once-a-minute stall to the Serverless
# layer, outside the engine's code, and run 8 compares the two.

locals {
  serverless = var.node_type == null
  endpoint = local.serverless ? {
    address = aws_elasticache_serverless_cache.this[0].endpoint[0].address
    port    = aws_elasticache_serverless_cache.this[0].endpoint[0].port
    } : {
    address = aws_elasticache_replication_group.this[0].configuration_endpoint_address
    port    = 6379
  }
}

resource "aws_elasticache_serverless_cache" "this" {
  count = local.serverless ? 1 : 0

  name                 = "${var.name_prefix}-cache"
  engine               = "valkey"
  major_engine_version = var.major_engine_version
  description          = "Engine state: idempotency, account history and rule catalog"

  subnet_ids         = var.data_subnet_ids
  security_group_ids = [var.security_group_id]

  # Upper limits, so a runaway test cannot grow the bill.
  cache_usage_limits {
    data_storage {
      maximum = var.max_data_storage_gb
      unit    = "GB"
    }
    ecpu_per_second {
      maximum = var.max_ecpu_per_second
    }
  }

  snapshot_retention_limit = var.snapshot_retention_days
}

resource "aws_elasticache_subnet_group" "this" {
  count = local.serverless ? 0 : 1

  name       = "${var.name_prefix}-cache"
  subnet_ids = var.data_subnet_ids
}

resource "aws_elasticache_replication_group" "this" {
  count = local.serverless ? 0 : 1

  replication_group_id = "${var.name_prefix}-cache"
  description          = "Engine state: idempotency, account history and rule catalog"
  engine               = "valkey"
  engine_version       = "${var.major_engine_version}.0"
  node_type            = var.node_type
  parameter_group_name = "default.valkey${var.major_engine_version}.cluster.on"
  port                 = 6379

  cluster_mode               = "enabled"
  num_node_groups            = 1
  replicas_per_node_group    = 1
  automatic_failover_enabled = true
  multi_az_enabled           = true

  subnet_group_name  = aws_elasticache_subnet_group.this[0].name
  security_group_ids = [var.security_group_id]

  transit_encryption_enabled = true
  at_rest_encryption_enabled = true

  snapshot_retention_limit = var.snapshot_retention_days
  apply_immediately        = true
}

moved {
  from = aws_elasticache_serverless_cache.this
  to   = aws_elasticache_serverless_cache.this[0]
}
