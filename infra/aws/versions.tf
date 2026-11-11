terraform {
  required_version = ">= 1.5.0"

  # Local state only. Do not add a backend here until Eason chooses an S3
  # state bucket. State files are gitignored.
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.70.0, < 6.0.0"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = var.tags
  }
}
