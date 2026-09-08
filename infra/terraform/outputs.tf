output "ec2_public_ip" {
  description = "Public IPv4 address of the OpsMind EC2 host."
  value       = aws_instance.opsmind_host.public_ip
}

output "api_endpoint" {
  description = "Base URL of the OpsMind FastAPI endpoint."
  value       = "http://${aws_instance.opsmind_host.public_ip}:8000"
}

output "sqs_queue_url" {
  description = "Amazon SQS Incident Queue URL."
  value       = aws_sqs_queue.incidents_queue.url
}

output "sqs_dlq_url" {
  description = "Amazon SQS Dead-Letter Queue (DLQ) URL."
  value       = aws_sqs_queue.incidents_dlq.url
}

output "dynamodb_table_name" {
  description = "Amazon DynamoDB Incidents Table Name."
  value       = aws_dynamodb_table.incidents.name
}

output "s3_bucket_name" {
  description = "Amazon S3 Artifacts Bucket Name."
  value       = aws_s3_bucket.artifacts.bucket
}

output "eventbridge_bus_name" {
  description = "Amazon EventBridge Custom Bus Name."
  value       = aws_cloudwatch_event_bus.opsmind_bus.name
}
