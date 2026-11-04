output "state_machine_arn" {
  value = one(aws_sfn_state_machine.reconciliation[*].arn)
}

output "spark_job_name" {
  value = one(aws_glue_job.match[*].name)
}

output "code_path" {
  description = "s3:// path of the code zip of the Spark jobs (services/reconciliation, services/analytics and shared)."
  value       = local.deploy ? "s3://${one(aws_s3_object.code[*].bucket)}/${one(aws_s3_object.code[*].key)}" : ""
}
