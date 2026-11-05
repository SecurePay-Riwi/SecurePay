provider "aws" {
  region = var.region

  # Project, environment and owner tags on every resource, as the
  # assignment requires (CT-03; infrastructure.mdx, "Tagging").
  default_tags {
    tags = {
      project     = "securepay"
      environment = var.environment
      owner       = var.owner
      managed_by  = "terraform"
    }
  }
}

locals {
  name_prefix = "securepay-${var.environment}"
  # SLOW_DECISION_MS of the engine and the slow-decision filter (HU-59).
  slow_decision_ms = 150
}

data "aws_availability_zones" "available" {
  state = "available"
}

module "network" {
  source = "../../modules/network"

  name_prefix        = local.name_prefix
  availability_zones = slice(data.aws_availability_zones.available.names, 0, 2)
}

module "security_groups" {
  source = "../../modules/security_groups"

  name_prefix = local.name_prefix
  vpc_id      = module.network.vpc_id
  engine_port = var.engine_port
}

# Budget alert (alarm 10 in infrastructure.mdx). AWS refreshes costs a few
# times a day, so the email can arrive hours after the spend: destroying the
# environment after each test is the real protection.
resource "aws_budgets_budget" "monthly" {
  name         = "${local.name_prefix}-budget"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Count usage paid with credits too: with credits subtracted, the spend
  # they cover shows as USD 0 and the alert would never fire.
  cost_types {
    include_credit = false
    include_refund = false
  }

  dynamic "notification" {
    for_each = var.budget_alert_percentages

    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = var.budget_emails
    }
  }
}

module "iam" {
  source = "../../modules/iam"

  name_prefix                 = local.name_prefix
  environment                 = var.environment
  create_github_oidc_provider = var.create_github_oidc_provider
}

module "storage" {
  source = "../../modules/storage"

  name_prefix   = local.name_prefix
  force_destroy = true

  # Object Lock does not accept less than 1 day of default retention. In dev
  # there is none, and each test object carries its own retain-until date
  # (1 hour), so destroy works once that hour has passed.
  evidence_default_retention_years = 0
}

module "database" {
  source = "../../modules/database"

  name_prefix           = local.name_prefix
  environment           = var.environment
  data_subnet_ids       = module.network.data_subnet_ids
  security_group_id     = module.security_groups.ids["rds"]
  multi_az              = var.database_multi_az
  backup_retention_days = var.database_backup_retention_days
  disposable            = true
}

module "ecr" {
  source = "../../modules/ecr"

  name_prefix  = local.name_prefix
  force_delete = true

  # apis: the securepay-apis image, pushed by that repository's deploy
  # workflow (role deploy-apis).
  repositories = ["engine", "generator", "admin", "apis"]

  # The consumers and the alerts task run the engine's image (HU-68); the
  # exchange-rates Lambda runs securepay-apis' image (HU-42).
  lambda_repositories = ["engine", "apis"]
}

module "cache" {
  source = "../../modules/cache"

  name_prefix             = local.name_prefix
  data_subnet_ids         = module.network.data_subnet_ids
  security_group_id       = module.security_groups.ids["cache"]
  snapshot_retention_days = 0
}

module "ecs" {
  source = "../../modules/ecs"

  name_prefix              = local.name_prefix
  vpc_id                   = module.network.vpc_id
  public_subnet_ids        = module.network.public_subnet_ids
  app_subnet_ids           = module.network.app_subnet_ids
  alb_security_group_id    = module.security_groups.ids["alb"]
  engine_security_group_id = module.security_groups.ids["engine"]
  admin_security_group_id  = module.security_groups.ids["admin"]
  domain_name              = var.domain_name
  container_insights       = false
  log_retention_days       = 14

  engine_repository_url     = module.ecr.repository_urls["engine"]
  engine_image_tag          = var.engine_image_tag
  engine_port               = var.engine_port
  engine_min_tasks          = var.engine_min_tasks
  engine_max_tasks          = var.engine_max_tasks
  engine_execution_role_arn = module.iam.role_arns["engine-execution"]
  engine_task_role_arn      = module.iam.role_arns["engine"]

  # Every decision goes to the decisions topic, which feeds the consumer
  # Lambdas (HU-68).
  engine_environment = {
    AWS_DEFAULT_REGION       = var.region
    VALKEY_URL               = module.cache.url
    VALKEY_CLUSTER           = "true"
    SNS_DECISIONES_TOPIC_ARN = module.messaging.decisions_topic_arn
    RATES_TABLE              = module.storage.exchange_rates_table
    # The decisions at least this slow are logged; the alarms use the same.
    SLOW_DECISION_MS = tostring(local.slow_decision_ms)
  }

  admin_repository_url     = module.ecr.repository_urls["admin"]
  admin_image_tag          = var.admin_image_tag
  admin_execution_role_arn = module.iam.role_arns["admin-execution"]
  admin_task_role_arn      = module.iam.role_arns["admin"]

  # securepay-seed in dev mode (100 users); it also exports the restricted
  # list to the list provider bucket.
  admin_environment = {
    AWS_DEFAULT_REGION = var.region
    SEED_MODE          = "dev"
    # 10,000 users (9,820 active accounts): the accounts of
    # infra/load/accounts.json, so the load test spreads its traffic as
    # production would instead of piling it on 98 accounts.
    SEED_USERS              = "10000"
    SEED_LIST_OUTPUT        = "s3"
    PROVEEDOR_LISTAS_BUCKET = module.storage.bucket_names["list-provider"]
  }
  admin_secrets = { DATABASE_URL = module.database.master_url_parameter_arn }
}

module "messaging" {
  source = "../../modules/messaging"

  name_prefix       = local.name_prefix
  supervisor_emails = var.supervisor_emails
  compliance_emails = var.compliance_emails
  treasury_emails   = var.treasury_emails
  alarm_emails      = var.budget_emails
}

# The consumers and the alerts task (HU-68), the reconciliation steps
# (HU-36) and the daily cache loader (HU-67),
# with the engine's image. Created once lambda_image_tag is set.
module "lambdas" {
  source = "../../modules/lambdas"

  name_prefix              = local.name_prefix
  repository_url           = module.ecr.repository_urls["engine"]
  image_tag                = var.lambda_image_tag
  role_arns                = module.iam.role_arns
  app_subnet_ids           = module.network.app_subnet_ids
  lambda_security_group_id = module.security_groups.ids["lambda"]
  queue_arns               = module.messaging.queue_arns
  cache_url                = module.cache.url

  # Each Lambda reads its own database password (MAG-361); db-bootstrap
  # creates the users and grants.
  database = {
    host                 = module.database.endpoint
    port                 = module.database.port
    name                 = module.database.database_name
    master_username      = module.database.master_username
    parameter_path       = module.database.parameter_path
    instance_resource_id = module.database.instance_resource_id
    password_versions    = module.database.password_versions
  }

  business_alerts_topic_arn = module.messaging.business_alerts_topic_arn
  ops_alarms_topic_arn      = module.messaging.ops_alarms_topic_arn
  datalake_bucket           = module.storage.bucket_names["datalake"]
  evidence_bucket           = module.storage.bucket_names["evidence"]
  evidence_retention_days   = "0.0035"
  case_due_minutes          = var.case_due_minutes
  log_retention_days        = 14

  apis_repository_url  = module.ecr.repository_urls["apis"]
  apis_image_tag       = var.apis_image_tag
  exchange_rates_table = module.storage.exchange_rates_table
}

# The rules and cases APIs for people (infrastructure.mdx): API Gateway
# (HTTP API) with a Cognito sign-in in front of their Lambdas. Created with
# the Lambdas (lambda_image_tag).
module "api" {
  source = "../../modules/api"

  name_prefix = local.name_prefix
  enabled     = var.lambda_image_tag != null
  rules_function = var.lambda_image_tag == null ? null : {
    name = module.lambdas.function_names["rules-api"]
    arn  = module.lambdas.function_arns["rules-api"]
  }
  cases_function = var.lambda_image_tag == null ? null : {
    name = module.lambdas.function_names["cases-api"]
    arn  = module.lambdas.function_arns["cases-api"]
  }
}

# The nightly reconciliation (HU-36): Step Functions at 02:00 Bogota, the
# match on AWS Glue (EMR is not on AWS's free account plan), the 06:30
# check and the failure alarm. Created with the Lambdas (lambda_image_tag).
module "reconciliation" {
  source = "../../modules/reconciliation"

  name_prefix = local.name_prefix
  enabled     = var.lambda_image_tag != null

  statement_reader_arn   = lookup(module.lambdas.function_arns, "statement-reader", "")
  difference_writer_arn  = lookup(module.lambdas.function_arns, "difference-writer", "")
  alerts_function_arn    = lookup(module.lambdas.function_arns, "alerts", "")
  state_machine_role_arn = module.iam.role_arns["reconciliation"]
  glue_job_role_arn      = module.iam.role_arns["glue-jobs"]
  scheduler_role_arn     = module.iam.role_arns["scheduler"]

  datalake_bucket           = module.storage.bucket_names["datalake"]
  artifacts_bucket          = module.storage.bucket_names["artifacts"]
  business_alerts_topic_arn = module.messaging.business_alerts_topic_arn
  ops_alarms_topic_arn      = module.messaging.ops_alarms_topic_arn

  repo_root      = "${path.root}/../../../.."
  schedule       = var.reconciliation_schedule
  check_schedule = var.reconciliation_check_schedule

  # The analytics steps after the store (HU-66).
  analytics_export_arn = lookup(module.lambdas.function_arns, "analytics-export", "")
  analytics_job_name   = "${local.name_prefix}-analytics"
  athena_workgroup     = module.analytics.athena_workgroup
  glue_database        = module.analytics.glue_database
  view_queries         = module.analytics.view_queries
}

# The analytics model (HU-66): the Glue catalog and the Athena workgroup
# always (Power BI can be set up first), the Spark job with the Lambdas.
# The nightly state machine runs export -> job -> views after the store.
module "analytics" {
  source = "../../modules/analytics"

  name_prefix       = local.name_prefix
  enabled           = var.lambda_image_tag != null
  glue_job_role_arn = module.iam.role_arns["glue-jobs"]
  datalake_bucket   = module.storage.bucket_names["datalake"]
  artifacts_bucket  = module.storage.bucket_names["artifacts"]
  code_path         = module.reconciliation.code_path
  repo_root         = "${path.root}/../../../.."
}

# Metrics, logs and alarms (HU-59): the dashboard securepay-dev, the
# alarms of infrastructure.mdx that do not live with their resource, and
# the saved Logs Insights queries. Every alarm e-mails -ops-alarms.
module "monitoring" {
  source = "../../modules/monitoring"

  name_prefix          = local.name_prefix
  ops_alarms_topic_arn = module.messaging.ops_alarms_topic_arn

  engine_deployed         = var.engine_image_tag != null
  alb_arn_suffix          = module.ecs.alb_arn_suffix
  target_group_arn_suffix = module.ecs.target_group_arn_suffix
  engine_log_group_name   = module.ecs.engine_log_group_name
  cluster_name            = module.ecs.cluster_name
  availability_zones      = slice(data.aws_availability_zones.available.names, 0, 2)

  queues                       = [for name in ["cases", "history", "analytics"] : "${local.name_prefix}-${name}"]
  lambda_function_names        = module.lambdas.function_names
  exchange_rates_deployed      = var.apis_image_tag != null
  exchange_rates_function_name = module.lambdas.exchange_rates_function_name
  state_machine_arn            = module.reconciliation.state_machine_arn
  db_instance_identifier       = "${local.name_prefix}-db"
  slow_decision_ms             = local.slow_decision_ms
}
