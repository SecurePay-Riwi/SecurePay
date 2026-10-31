# RDS PostgreSQL of infrastructure.mdx ("Data") with the backup strategy of
# "Database backup strategy". Passwords are generated here and stored as
# SecureString parameters; they also end up in the Terraform state, which is
# why the state is never committed or shared.

locals {
  parameter_path = "/securepay/${var.environment}/rds"
}

resource "aws_db_subnet_group" "this" {
  name       = "${var.name_prefix}-db"
  subnet_ids = var.data_subnet_ids
}

resource "aws_db_parameter_group" "this" {
  name   = "${var.name_prefix}-postgres16"
  family = "postgres16"

  # TLS required for every connection. AWS stores this parameter as
  # pending-reboot; without it every plan after an apply shows a change.
  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "pending-reboot"
  }
}

# RDS does not accept / @ " or spaces in the master password.
resource "random_password" "master" {
  length           = 32
  special          = true
  override_special = "!#$%^&*()-_=+[]{}<>:?"
}

resource "aws_ssm_parameter" "master_password" {
  name        = "${local.parameter_path}/master-password"
  description = "Master user password. Only the admin task reads it."
  type        = "SecureString"
  value       = random_password.master.result
}

resource "random_password" "component" {
  for_each = toset(var.component_users)

  length           = 32
  special          = true
  override_special = "!#$%^&*()-_=+[]{}<>:?"
}

resource "aws_ssm_parameter" "component_password" {
  for_each = random_password.component

  name        = "${local.parameter_path}/${each.key}"
  description = "Password of the database user ${each.key}; only its component's role reads it."
  type        = "SecureString"
  value       = each.value.result
}

resource "aws_db_instance" "this" {
  identifier     = "${var.name_prefix}-db"
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.instance_class
  multi_az       = var.multi_az

  db_name  = "securepay"
  username = "securepay_admin"
  password = random_password.master.result
  port     = 5432

  allocated_storage = var.allocated_storage_gb
  storage_type      = "gp3"
  storage_encrypted = true

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [var.security_group_id]
  parameter_group_name   = aws_db_parameter_group.this.name
  publicly_accessible    = false

  # Times in UTC. Reconciliation runs 02:00-07:00 Bogota (07:00-12:00 UTC):
  # backups at 00:00 Bogota, maintenance on Sunday at 11:00 Bogota.
  backup_retention_period = var.backup_retention_days
  backup_window           = "05:00-06:00"
  maintenance_window      = "sun:16:00-sun:17:00"
  copy_tags_to_snapshot   = true

  auto_minor_version_upgrade = true
  deletion_protection        = !var.disposable
  skip_final_snapshot        = var.disposable
  final_snapshot_identifier  = var.disposable ? null : "${var.name_prefix}-db-final"
  delete_automated_backups   = var.disposable
  apply_immediately          = var.disposable
}

# Full connection URL for the services that take DATABASE_URL (the admin
# task and, temporarily, the engine). ECS injects a parameter as a whole
# value, so the password goes inside the URL here and never as plain text
# in a task definition.
resource "aws_ssm_parameter" "master_url" {
  name        = "${local.parameter_path}/master-url"
  description = "DATABASE_URL of the master user, with TLS required."
  type        = "SecureString"
  value       = "postgresql://${aws_db_instance.this.username}:${urlencode(random_password.master.result)}@${aws_db_instance.this.address}:${aws_db_instance.this.port}/${aws_db_instance.this.db_name}?sslmode=require"
}
