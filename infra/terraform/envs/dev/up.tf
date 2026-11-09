# One `terraform apply` brings dev up (MAG-308). On the computer that
# applies it (Docker running, the AWS CLI signed in, uv), the apply:
#
#   1. tags each image with its repository's short commit (data "external");
#   2. builds and pushes the engine, the seed and securepay-apis to ECR
#      when that tag is not there yet (terraform_data.image);
#   3. after db-bootstrap, seeds RDS with the admin task (terraform_data.seed),
#      loads the cache (list-loader) and today's exchange rates, and writes
#      the fixed rates of 2026-10-01, the day of the test transactions;
#   4. uploads PaySim and fraudTest from the securepay-csv clone to the raw
#      layer and loads their sample into RDS with the seed's Kaggle ETL
#      (terraform_data.kaggle_etl), so the nightly run measures the rules
#      against them (MAG-312);
#   5. creates the access key of the powerbi user and writes it to the AWS
#      CLI profile securepay-powerbi of that computer, for Power BI.
#
# Set build_images = false to push the images yourself and give their tags
# in engine_image_tag, admin_image_tag, lambda_image_tag and apis_image_tag
# (deploy-aws-terraform.mdx, "Without Docker on this computer"). A tag given
# in a variable always wins over the built one.

locals {
  repo_root = abspath("${path.root}/../../../..")
  # Run from the scripts folder (working_dir), with no quotes and no path
  # in the command: on Windows Terraform hands the command to cmd with its
  # quotes escaped as \", so a quoted path with spaces broke into pieces.
  # A path with spaces goes in an environment variable instead.
  scripts_dir = abspath("${path.root}/../../scripts")
  dev_up      = "uv run --no-project python dev_up.py"

  # {engine, admin, apis}: the commit of each clone, "" when the clone is
  # not beside SecurePay (that image is not built).
  built_tags = var.build_images ? data.external.image_tags[0].result : {}

  given_tags = {
    engine = var.engine_image_tag
    admin  = var.admin_image_tag
    apis   = var.apis_image_tag
  }
  chosen_tags = { for name, tag in local.given_tags : name => coalesce(tag, lookup(local.built_tags, name, ""), "-") }
  image_tags  = { for name, tag in local.chosen_tags : name => tag == "-" ? null : tag }

  # Built here: the images whose tag no variable gives.
  build = { for name, tag in local.built_tags : name => tag if tag != "" && local.given_tags[name] == null }

  # The Lambdas run the engine's image. Without build_images they still
  # wait for lambda_image_tag, as in the step-by-step deploy.
  lambda_image_tag = var.lambda_image_tag != null ? var.lambda_image_tag : (var.build_images ? local.image_tags.engine : null)

  build_contexts = {
    engine = local.repo_root
    admin  = "${dirname(local.repo_root)}/securepay-seed"
    apis   = "${dirname(local.repo_root)}/securepay-apis"
  }

  # The repository URL reaches ECS and the Lambdas through the push, so
  # nothing uses an image before it is in ECR.
  repository_urls = {
    for name in ["engine", "admin", "apis"] :
    name => try(terraform_data.image[name].output.url, module.ecr.repository_urls[name])
  }

  load_data = var.load_data_on_apply && local.image_tags.admin != null && local.lambda_image_tag != null
}

data "external" "image_tags" {
  count = var.build_images ? 1 : 0

  program = ["uv", "run", "--no-project", "python", "${path.root}/../../scripts/dev_up.py", "tags"]
  query   = { securepay = local.repo_root }
}

resource "terraform_data" "image" {
  for_each = local.build

  triggers_replace = each.value
  input            = { url = module.ecr.repository_urls[each.key], tag = each.value }

  provisioner "local-exec" {
    working_dir = local.scripts_dir
    command     = "${local.dev_up} push --repository ${self.input.url} --tag ${self.input.tag} --region ${var.region}"
    environment = { DEV_UP_CONTEXT = local.build_contexts[each.key] }
  }
}

# The seed (SEED_RESET: it empties the seed tables first), again whenever
# the seed image or the database changes. db-bootstrap goes first: the
# seed only truncates, so its grants stay.
resource "terraform_data" "seed" {
  count = local.load_data ? 1 : 0

  triggers_replace = [module.ecs.admin_task_revision, module.database.instance_resource_id]
  input            = module.lambdas.db_bootstrap_result

  provisioner "local-exec" {
    working_dir = local.scripts_dir
    command     = "${local.dev_up} run-task --cluster ${module.ecs.cluster_name} --task-definition ${module.ecs.admin_task_family}:${module.ecs.admin_task_revision} --subnets ${join(",", module.network.app_subnet_ids)} --security-group ${module.security_groups.ids["admin"]} --region ${var.region}"
  }

  # The NAT routes too, or the task cannot pull its image.
  depends_on = [module.network]
}

# The Kaggle datasets (load_kaggle, MAG-312): the CSVs that securepay-csv's
# loader leaves in its clone (data/kaggle, never committed), uploaded as is
# to the raw layer with the keys that loader uses, and then the seed's
# Kaggle ETL in the admin task: it downloads them, checks their SHA-256 and
# adds its 70,000 rows to `transacciones`. Again after every new seed (the
# seed empties that table) or new CSV. Nothing happens when the CSVs are
# not there: run `uv run python -m securepay_csv.kaggle_datasets` once in
# securepay-csv first.
locals {
  kaggle_dir = coalesce(var.kaggle_dir, "${dirname(local.repo_root)}/securepay-csv/data/kaggle")
  kaggle_csv = {
    "raw/kaggle/paysim/paysim.csv"               = "${local.kaggle_dir}/PS_20174392719_1491204439457_log.csv"
    "raw/kaggle/sparkov/fraudtest/fraudTest.csv" = "${local.kaggle_dir}/fraudTest.csv"
  }
  load_kaggle = var.load_kaggle && local.load_data && alltrue([for file in values(local.kaggle_csv) : fileexists(file)])
}

resource "aws_s3_object" "kaggle" {
  for_each = local.load_kaggle ? local.kaggle_csv : {}

  bucket = module.storage.bucket_names["datalake"]
  key    = each.key
  source = each.value
  # Not etag: the AWS provider uploads files this size in parts, and the
  # etag of a multipart object is not the file's MD5.
  source_hash = filemd5(each.value)
}

resource "terraform_data" "kaggle_etl" {
  count = local.load_kaggle ? 1 : 0

  triggers_replace = concat([terraform_data.seed[0].id], [for key in sort(keys(local.kaggle_csv)) : aws_s3_object.kaggle[key].source_hash])

  provisioner "local-exec" {
    working_dir = local.scripts_dir
    command     = "${local.dev_up} run-task --cluster ${module.ecs.cluster_name} --task-definition ${module.ecs.admin_task_family}:${module.ecs.admin_task_revision} --subnets ${join(",", module.network.app_subnet_ids)} --security-group ${module.security_groups.ids["admin"]} --region ${var.region} --timeout-minutes 40 --kaggle-raw-dir s3://${module.storage.bucket_names["datalake"]}/raw/kaggle"
  }

  depends_on = [module.network]
}

# Accounts, merchants and the restricted list into the cache now, instead
# of at 01:00 Bogota; again after a new seed or a new cache.
resource "aws_lambda_invocation" "list_loader" {
  count = local.load_data ? 1 : 0

  function_name = module.lambdas.function_names["list-loader"]
  input         = jsonencode({ seed = terraform_data.seed[0].id, cache = module.cache.address })
}

# Today's exchange rates now, instead of at 11:00 Bogota.
resource "aws_lambda_invocation" "exchange_rates" {
  count = var.load_data_on_apply && local.image_tags.apis != null ? 1 : 0

  function_name = module.lambdas.exchange_rates_function_name
  input         = jsonencode({})
}

# The day of smoke-transaction.json and restricted-transaction.json: the
# fixed rates of currency.RATES_PER_USD, so their decisions convert with a
# rate of their own day instead of raising the fixed-rates alarm. No
# expires_at: the TTL never removes it.
resource "aws_dynamodb_table_item" "test_day_rates" {
  count = var.load_data_on_apply ? 1 : 0

  table_name = module.storage.exchange_rates_table
  hash_key   = "base"
  range_key  = "rate_date"
  item = jsonencode({
    base      = { S = "USD" }
    rate_date = { S = "2026-10-01" }
    rates = { M = {
      USD = { N = "1" }
      COP = { N = "3317.65" }
      EUR = { N = "0.88284" }
      JPY = { N = "157.76" }
    } }
    source = { S = "fixed rates of 2026-10-01 (currency.RATES_PER_USD), written by Terraform" }
  })
}

# The demo day (load_demo_day): the fixture day 2026-10-05 of the
# reconciliation (partner files and decisions, the 6 differences of its
# answer key) and of the analytics (more decisions and the generator's
# labels), then one run of the nightly state machine for that day. With
# both sets the treasury e-mail says 19 differences: the analytics
# decisions add 13 approved transactions no partner reported.
locals {
  demo_files = var.load_demo_day && local.lambda_image_tag != null ? merge(
    { for f in fileset("${local.repo_root}/services/reconciliation/tests/fixtures/extractos", "**") :
    "raw/extractos/${f}" => "${local.repo_root}/services/reconciliation/tests/fixtures/extractos/${f}" },
    { for f in fileset("${local.repo_root}/services/reconciliation/tests/fixtures/decisiones", "**") :
    "raw/decisiones/${f}" => "${local.repo_root}/services/reconciliation/tests/fixtures/decisiones/${f}" },
    { for f in fileset("${local.repo_root}/services/analytics/tests/fixtures/raw", "{decisiones,labels}/**") :
    "raw/${f}" => "${local.repo_root}/services/analytics/tests/fixtures/raw/${f}" },
  ) : {}
}

resource "aws_s3_object" "demo_day" {
  for_each = local.demo_files

  bucket = module.storage.bucket_names["datalake"]
  key    = each.key
  source = each.value
  etag   = filemd5(each.value)
}

# Started once (again only if a fixture changes); the apply does not wait
# for the run, which takes 5 to 10 minutes.
resource "terraform_data" "demo_day_run" {
  count = length(local.demo_files) > 0 ? 1 : 0

  triggers_replace = [for key in sort(keys(local.demo_files)) : aws_s3_object.demo_day[key].etag]

  provisioner "local-exec" {
    working_dir = local.scripts_dir
    command     = "${local.dev_up} start-day --state-machine ${module.reconciliation.state_machine_arn} --day 2026-10-05 --region ${var.region}"
  }

  # The seed and the Kaggle rows first: the run's store, export and
  # Kaggle metrics read RDS.
  depends_on = [terraform_data.seed, terraform_data.kaggle_etl]
}

# Power BI's key (powerbi_profile). The access key of the powerbi user,
# written to that profile of ~/.aws/credentials on the computer that
# applies, which Power BI's DSN reads (AwsProfile): after the apply,
# Refresh in Power BI is enough. The secret is in the local state, like the
# database passwords; it goes to the script in environment variables, never
# in the command line or the output. Destroy deletes the key; the profile
# stays until the next apply overwrites it.
resource "aws_iam_access_key" "powerbi" {
  count = var.powerbi_profile != null ? 1 : 0

  user = module.iam.powerbi_user
}

resource "terraform_data" "powerbi_profile" {
  count = var.powerbi_profile != null ? 1 : 0

  triggers_replace = [aws_iam_access_key.powerbi[0].id, var.powerbi_profile]

  provisioner "local-exec" {
    working_dir = local.scripts_dir
    command     = "${local.dev_up} aws-profile --profile ${var.powerbi_profile} --region ${var.region}"
    environment = {
      POWERBI_ACCESS_KEY_ID     = aws_iam_access_key.powerbi[0].id
      POWERBI_SECRET_ACCESS_KEY = aws_iam_access_key.powerbi[0].secret
    }
  }
}
