output "cluster_name" { value = module.eks.cluster_name }
output "ecr_repository_url" { value = aws_ecr_repository.app.repository_url }
output "postgres_endpoint" { value = aws_db_instance.postgres.address }
output "redis_endpoint" { value = aws_elasticache_replication_group.redis.primary_endpoint_address }
output "workload_role_arn" { value = module.workload_irsa.iam_role_arn }
output "application_secret_arn" { value = aws_secretsmanager_secret.app.arn }
