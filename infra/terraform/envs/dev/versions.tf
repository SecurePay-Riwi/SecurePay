terraform {
  required_version = ">= 1.9.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "5.80.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "2.7.1"
    }
    external = {
      source  = "hashicorp/external"
      version = "2.3.4"
    }
    random = {
      source  = "hashicorp/random"
      version = "3.6.3"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "4.0.6"
    }
  }

  # Local state for now (it is in .gitignore). A remote S3 state bucket
  # (securepay-tfstate in infrastructure.mdx) is decided separately.
}
