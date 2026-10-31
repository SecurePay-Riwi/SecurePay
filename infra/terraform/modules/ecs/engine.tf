# The engine service exists only once an image tag is given: the first apply
# creates the repositories, the image is pushed, and the next apply (with
# engine_image_tag) starts the tasks. A task never starts without its image.

locals {
  deploy_engine = var.engine_image_tag != null
}

resource "aws_ecs_task_definition" "engine" {
  count = local.deploy_engine ? 1 : 0

  family                   = "${var.name_prefix}-engine"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.engine_cpu
  memory                   = var.engine_memory
  execution_role_arn       = var.engine_execution_role_arn
  task_role_arn            = var.engine_task_role_arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name         = "engine"
    image        = "${var.engine_repository_url}:${var.engine_image_tag}"
    essential    = true
    portMappings = [{ containerPort = var.engine_port, protocol = "tcp" }]
    command      = ["uvicorn", "services.decision_engine.main:app", "--host", "0.0.0.0", "--port", tostring(var.engine_port)]
    environment  = local.engine_environment
    secrets      = local.engine_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.this["engine"].name
        awslogs-region        = local.region
        awslogs-stream-prefix = "engine"
      }
    }
  }])
}

resource "aws_ecs_service" "engine" {
  count = local.deploy_engine ? 1 : 0

  name            = "engine"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.engine[0].arn
  desired_count   = var.engine_min_tasks
  launch_type     = "FARGATE"

  # Replace tasks without dropping below the current count; roll back on
  # its own if the new tasks never become healthy.
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # Time for uvicorn to start before the load balancer checks count.
  health_check_grace_period_seconds = 60

  network_configuration {
    subnets          = var.app_subnet_ids
    security_groups  = [var.engine_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.engine.arn
    container_name   = "engine"
    container_port   = var.engine_port
  }

  propagate_tags = "SERVICE"

  # Autoscaling moves desired_count; Terraform must not undo it.
  lifecycle {
    ignore_changes = [desired_count]
  }

  depends_on = [aws_lb_listener.https]
}

resource "aws_appautoscaling_target" "engine" {
  count = local.deploy_engine ? 1 : 0

  service_namespace  = "ecs"
  scalable_dimension = "ecs:service:DesiredCount"
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.engine[0].name}"
  min_capacity       = var.engine_min_tasks
  max_capacity       = var.engine_max_tasks
}

resource "aws_appautoscaling_policy" "engine_cpu" {
  count = local.deploy_engine ? 1 : 0

  name               = "${var.name_prefix}-engine-cpu"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.engine[0].service_namespace
  scalable_dimension = aws_appautoscaling_target.engine[0].scalable_dimension
  resource_id        = aws_appautoscaling_target.engine[0].resource_id

  target_tracking_scaling_policy_configuration {
    target_value       = var.engine_cpu_target
    scale_out_cooldown = 60
    scale_in_cooldown  = 300

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}
