variable "aws_region" {
  type        = string
  description = "AWS region for all regional resources."
  default     = "us-west-2"
}

variable "environment" {
  type        = string
  description = "Environment name."
  default     = "dev"

  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment must be dev or prod"
  }
}

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}

variable "cluster_version" {
  type    = string
  default = "1.32"
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "redis_node_type" {
  type    = string
  default = "cache.t4g.micro"
}

variable "alert_email" {
  type        = string
  description = "Optional email address for AWS budget alerts."
  default     = ""
}
