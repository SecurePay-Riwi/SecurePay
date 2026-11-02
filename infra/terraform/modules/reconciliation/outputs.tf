output "state_machine_arn" {
  value = one(aws_sfn_state_machine.reconciliation[*].arn)
}

output "spark_job_name" {
  value = one(aws_glue_job.match[*].name)
}
