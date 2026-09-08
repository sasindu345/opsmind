resource "aws_cloudwatch_log_group" "opsmind_logs" {
  name              = "/aws/opsmind/${var.environment}"
  retention_in_days = var.log_retention_days
}

# Metric Alarm: High SQS Queue Depth
resource "aws_cloudwatch_metric_alarm" "sqs_high_depth_alarm" {
  alarm_name          = "${local.name_prefix}-sqs-high-depth"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Average"
  threshold           = 100
  alarm_description   = "OpsMind incident queue backlog exceeded 100 messages"

  dimensions = {
    QueueName = aws_sqs_queue.incidents_queue.name
  }
}

# Metric Alarm: Dead Letter Queue Messages Received
resource "aws_cloudwatch_metric_alarm" "dlq_messages_alarm" {
  alarm_name          = "${local.name_prefix}-dlq-messages-detected"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Dead-letter queue received unprocessable poison pill messages"

  dimensions = {
    QueueName = aws_sqs_queue.incidents_dlq.name
  }
}
