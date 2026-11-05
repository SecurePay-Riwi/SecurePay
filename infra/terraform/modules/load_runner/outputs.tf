output "instance_id" {
  value = one(aws_instance.this[*].id)
}

output "load_test_command" {
  description = "Runs the full test (50, 150 and 300 tx/s, 5 minutes each) on the machine and prints the command id."
  value       = var.enabled ? "aws ssm send-command --instance-ids ${aws_instance.this[0].id} --document-name AWS-RunShellScript --parameters commands=securepay-load --query Command.CommandId --output text" : null
}
