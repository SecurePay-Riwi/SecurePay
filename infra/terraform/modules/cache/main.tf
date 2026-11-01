# ElastiCache Serverless for Valkey (infrastructure.mdx, "Data"): in the data
# subnets, reachable only from sg-engine and sg-lambda on 6379 (primary) and
# 6380 (reader). Encryption in transit is always on, so clients connect with
# rediss://. Serverless only accepts clients that speak the cluster protocol.

resource "aws_elasticache_serverless_cache" "this" {
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
