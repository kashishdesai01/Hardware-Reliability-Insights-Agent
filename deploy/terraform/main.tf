data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

locals {
  name = "hria-${var.environment}"
  azs  = slice(data.aws_availability_zones.available.names, 0, 3)
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.21"

  name = local.name
  cidr = var.vpc_cidr
  azs  = local.azs

  private_subnets  = [for index, _ in local.azs : cidrsubnet(var.vpc_cidr, 4, index)]
  public_subnets   = [for index, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, index + 48)]
  database_subnets = [for index, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, index + 64)]

  enable_nat_gateway           = true
  single_nat_gateway           = var.environment == "dev"
  enable_dns_hostnames         = true
  create_database_subnet_group = true

  public_subnet_tags = {
    "kubernetes.io/role/elb" = "1"
  }
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = "1"
  }
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.37"

  cluster_name                             = local.name
  cluster_version                          = var.cluster_version
  cluster_endpoint_public_access           = true
  enable_cluster_creator_admin_permissions = true
  enable_irsa                              = true

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  eks_managed_node_groups = {
    default = {
      instance_types = var.environment == "prod" ? ["m7i.large"] : ["m7i.large"]
      min_size       = var.environment == "prod" ? 3 : 1
      max_size       = var.environment == "prod" ? 8 : 3
      desired_size   = var.environment == "prod" ? 3 : 1
    }
  }
}

resource "aws_security_group" "data" {
  name        = "${local.name}-data"
  description = "Database access from EKS nodes only"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description     = "Postgres from EKS nodes"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
  }

  ingress {
    description     = "Redis from EKS nodes"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "random_password" "database" {
  length  = 32
  special = true
}

resource "aws_db_instance" "postgres" {
  identifier                   = "${local.name}-postgres"
  engine                       = "postgres"
  engine_version               = "16"
  instance_class               = var.db_instance_class
  allocated_storage            = var.environment == "prod" ? 100 : 20
  max_allocated_storage        = var.environment == "prod" ? 500 : 100
  storage_encrypted            = true
  db_name                      = "hria"
  username                     = "hria"
  password                     = random_password.database.result
  db_subnet_group_name         = module.vpc.database_subnet_group_name
  vpc_security_group_ids       = [aws_security_group.data.id]
  multi_az                     = var.environment == "prod"
  backup_retention_period      = var.environment == "prod" ? 14 : 1
  deletion_protection          = var.environment == "prod"
  skip_final_snapshot          = var.environment != "prod"
  performance_insights_enabled = true
  apply_immediately            = var.environment == "dev"
}

resource "aws_elasticache_subnet_group" "redis" {
  name       = local.name
  subnet_ids = module.vpc.database_subnets
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id       = "${local.name}-redis"
  description                = "HRIA arq queue and ephemeral result cache"
  node_type                  = var.redis_node_type
  port                       = 6379
  parameter_group_name       = "default.redis7"
  subnet_group_name          = aws_elasticache_subnet_group.redis.name
  security_group_ids         = [aws_security_group.data.id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  automatic_failover_enabled = var.environment == "prod"
  multi_az_enabled           = var.environment == "prod"
  num_cache_clusters         = var.environment == "prod" ? 2 : 1
}

resource "aws_ecr_repository" "app" {
  name                 = "hria"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_secretsmanager_secret" "app" {
  name                    = "${local.name}/application"
  recovery_window_in_days = var.environment == "prod" ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    DATABASE_URL = "postgresql+psycopg://hria:${urlencode(random_password.database.result)}@${aws_db_instance.postgres.address}:5432/hria"
    REDIS_URL    = "rediss://${aws_elasticache_replication_group.redis.primary_endpoint_address}:6379/0"
  })
}

module "workload_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.60"

  role_name = "${local.name}-workload"
  role_policy_arns = {
    secret_read = aws_iam_policy.secret_read.arn
  }
  oidc_providers = {
    cluster = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["hria:hria"]
    }
  }
}

resource "aws_iam_policy" "secret_read" {
  name = "${local.name}-secret-read"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = aws_secretsmanager_secret.app.arn
    }]
  })
}

resource "aws_budgets_budget" "monthly" {
  name         = "${local.name}-monthly"
  budget_type  = "COST"
  limit_amount = var.environment == "prod" ? "750" : "250"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = var.alert_email == "" ? [] : [var.alert_email]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = 80
      threshold_type             = "PERCENTAGE"
      notification_type          = "FORECASTED"
      subscriber_email_addresses = [notification.value]
    }
  }
}
