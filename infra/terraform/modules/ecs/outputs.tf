output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "alb_dns_name" {
  description = "Public name of the load balancer: https://<this>/health"
  value       = aws_lb.this.dns_name
}

output "certificate_validation_records" {
  description = "With a domain: the DNS record that proves it to ACM (add it at the DNS provider)."
  value = var.domain_name == null ? [] : [
    for option in aws_acm_certificate.domain[0].domain_validation_options : {
      name  = option.resource_record_name
      type  = option.resource_record_type
      value = option.resource_record_value
    }
  ]
}

output "admin_run_task_command" {
  description = "Command that seeds the database with the admin task."
  value = var.admin_image_tag == null ? null : join(" ", [
    "aws ecs run-task",
    "--cluster ${aws_ecs_cluster.this.name}",
    "--launch-type FARGATE",
    "--task-definition ${aws_ecs_task_definition.admin[0].family}",
    "--network-configuration \"awsvpcConfiguration={subnets=[${join(",", var.app_subnet_ids)}],securityGroups=[${var.admin_security_group_id}],assignPublicIp=DISABLED}\"",
  ])
}
