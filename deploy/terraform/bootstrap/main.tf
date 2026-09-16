terraform {
  required_version = ">= 1.10.0"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.90" }
    random = { source = "hashicorp/random", version = "~> 3.7" }
  }
}

provider "aws" { region = var.aws_region }
data "aws_caller_identity" "current" {}
resource "random_id" "suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "state" {
  bucket = "hria-tfstate-${data.aws_caller_identity.current.account_id}-${random_id.suffix.hex}"
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

variable "aws_region" {
  type    = string
  default = "us-west-2"
}

output "state_bucket" {
  value = aws_s3_bucket.state.bucket
}
