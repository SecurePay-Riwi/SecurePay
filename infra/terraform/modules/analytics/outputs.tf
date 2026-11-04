output "job_name" {
  description = "Name of the analytics Glue job (null until enabled)."
  value       = one(aws_glue_job.analytics[*].name)
}

output "glue_database" {
  description = "Glue catalog database of the analytics model (GLUE_DATABASE)."
  value       = aws_glue_catalog_database.analytics.name
}

output "athena_workgroup" {
  description = "Athena workgroup of the views and Power BI (ATHENA_WORKGROUP)."
  value       = aws_athena_workgroup.powerbi.name
}

output "view_queries" {
  description = "The CREATE OR REPLACE VIEW of each view, without comments, in q1..q6 order: the nightly state machine runs them."
  value       = local.view_queries
}
