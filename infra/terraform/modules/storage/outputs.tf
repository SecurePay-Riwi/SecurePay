output "bucket_names" {
  description = "Bucket name by purpose: datalake, evidence, list-provider, artifacts."
  value       = { for key, bucket in aws_s3_bucket.this : key => bucket.id }
}
