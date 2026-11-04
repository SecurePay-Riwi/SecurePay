# The analytics model in AWS (HU-66): the Spark job that builds it, the
# Glue catalog that describes it and the Athena workgroup Power BI queries.
#
#   Step Functions securepay-<env>-reconciliation, after the store:
#     ExportAnalytics  Lambda analytics-export   PostgreSQL -> raw/cases, raw/reconciliation
#     BuildAnalytics   Glue job -analytics       raw -> curated -> analytics + quality checks
#     RefreshViews     Athena                    CREATE OR REPLACE VIEW q1..q6
#
# The tables come from shared/analytics.py through tables.json
# (python -m services.analytics.catalog), never from a crawler. Daily
# tables use partition projection on fecha=<day>/: Athena finds the
# partitions from the path, nobody registers them.

locals {
  entry_point_key = "jobs/analytics/analytics_job.py"

  tables = jsondecode(file("${path.module}/tables.json"))

  # The views of services/analytics/sql/, in q1..q6 order, without their
  # comment lines and the final semicolon (Athena runs one statement).
  view_files = sort(fileset(var.repo_root, "services/analytics/sql/q*_*.sql"))
  view_queries = [
    for f in local.view_files : trimsuffix(trimspace(join("\n", [
      for line in split("\n", file("${var.repo_root}/${f}")) : line if !startswith(trimspace(line), "--")
    ])), ";")
  ]
}

resource "aws_glue_catalog_database" "analytics" {
  name        = "${replace(var.name_prefix, "-", "_")}_analytics"
  description = "SecurePay analytics model (shared/analytics.py): the tables of s3://${var.datalake_bucket}/analytics/ and the views q1..q6."
}

resource "aws_glue_catalog_table" "this" {
  for_each = local.tables

  name          = each.key
  database_name = aws_glue_catalog_database.analytics.name
  description   = each.value.description
  table_type    = "EXTERNAL_TABLE"

  parameters = merge(
    { EXTERNAL = "TRUE", classification = "parquet", "parquet.compression" = "SNAPPY" },
    each.value.partition == null ? {} : {
      "projection.enabled"             = "true"
      "projection.fecha.type"          = "date"
      "projection.fecha.format"        = "yyyy-MM-dd"
      "projection.fecha.range"         = "2026-01-01,NOW"
      "projection.fecha.interval"      = "1"
      "projection.fecha.interval.unit" = "DAYS"
      "storage.location.template"      = "s3://${var.datalake_bucket}/${each.value.location}fecha=$${fecha}/"
    },
  )

  dynamic "partition_keys" {
    for_each = each.value.partition == null ? [] : [each.value.partition]

    content {
      name    = partition_keys.value
      type    = "string"
      comment = "Folder fecha=<day>/ written by the Spark job (partition projection)."
    }
  }

  storage_descriptor {
    location      = "s3://${var.datalake_bucket}/${each.value.location}"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    dynamic "columns" {
      for_each = each.value.columns

      content {
        name    = columns.value.name
        type    = columns.value.type
        comment = columns.value.comment
      }
    }
  }
}

# The workgroup of the views and of Power BI (D10): its results go to
# athena-results/powerbi/, the only results path the powerbi user may use,
# and no query may scan more than bytes_scanned_cutoff.
resource "aws_athena_workgroup" "powerbi" {
  name          = "${var.name_prefix}-powerbi"
  description   = "Views q1..q6 of the analytics model; Power BI queries them here."
  force_destroy = true

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = var.bytes_scanned_cutoff

    engine_version {
      selected_engine_version = "Athena engine version 3"
    }

    result_configuration {
      output_location = "s3://${var.datalake_bucket}/athena-results/powerbi/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}

resource "aws_s3_object" "entry_point" {
  count = var.enabled ? 1 : 0

  bucket      = var.artifacts_bucket
  key         = local.entry_point_key
  source      = "${var.repo_root}/infra/spark/analytics_job.py"
  source_hash = filemd5("${var.repo_root}/infra/spark/analytics_job.py")
}

# Billed per second only while a run lasts (1 minute minimum), like the
# reconciliation's match: a few cents a night.
resource "aws_glue_job" "analytics" {
  count = var.enabled ? 1 : 0

  name              = "${var.name_prefix}-analytics"
  description       = "Builds a day of the analytics model and checks its quality (services/analytics/etl.py, quality.py)."
  role_arn          = var.glue_job_role_arn
  glue_version      = var.glue_version
  worker_type       = var.worker_type
  number_of_workers = var.workers
  timeout           = var.job_timeout_minutes
  max_retries       = 0

  command {
    name            = "glueetl"
    script_location = "s3://${var.artifacts_bucket}/${local.entry_point_key}"
    python_version  = "3"
  }

  default_arguments = {
    "--job-language"                     = "python"
    "--extra-py-files"                   = var.code_path
    "--additional-python-modules"        = var.python_modules
    "--enable-continuous-cloudwatch-log" = "true"
  }

  execution_property {
    max_concurrent_runs = 1
  }

  depends_on = [aws_s3_object.entry_point]
}
