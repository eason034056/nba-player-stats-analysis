terraform {
  required_version = ">= 1.5.0"

  # State stays on disk until Eason creates a state bucket and migrates.
  # An active backend block would make plain `terraform init` demand that
  # bucket and would stop the local state that is already applied.
  # A backend block cannot read var.environment, so the key is not written
  # here. backend-dev.hcl.example and backend-prod.hcl.example each set one
  # key. When the bucket exists, uncomment the block and migrate only the
  # current stack:
  #   terraform init -migrate-state -backend-config=backend-dev.hcl
  # Do not migrate this state with backend-prod.hcl.
  # backend "s3" {}

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.70.0, < 6.0.0"
    }
  }
}

provider "aws" {
  region = var.region

  # Environment is merged last so a tfvars tags map that only repeats
  # Project and ManagedBy still receives it. Tag updates are in place.
  # default_tags do not apply to data sources, so the default VPC is not tagged.
  default_tags {
    tags = merge(var.tags, {
      Environment = var.environment
    })
  }
}
