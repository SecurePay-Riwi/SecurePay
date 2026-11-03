output "repository_urls" {
  description = "Repository URL by image (engine, generator, admin, apis), for docker push."
  value       = { for name, repo in aws_ecr_repository.this : name => repo.repository_url }
}
