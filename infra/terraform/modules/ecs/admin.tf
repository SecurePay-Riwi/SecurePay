# Admin task: runs once on demand (aws ecs run-task) to seed the database,
# with the securepay-seed image. Fargate bills it only while it runs.

resource "aws_ecs_task_definition" "admin" {
  count = var.admin_image_tag != null ? 1 : 0

  family                   = "${var.name_prefix}-admin"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = var.admin_execution_role_arn
  task_role_arn            = var.admin_task_role_arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name        = "admin"
    image       = "${var.admin_repository_url}:${var.admin_image_tag}"
    essential   = true
    environment = local.admin_environment
    secrets     = local.admin_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.this["admin"].name
        awslogs-region        = local.region
        awslogs-stream-prefix = "admin"
      }
    }
  }])
}
