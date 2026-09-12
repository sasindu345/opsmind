resource "aws_sqs_queue" "incidents_dlq" {
  name                      = "${local.name_prefix}-incidents-dlq"
  message_retention_seconds = 1209600 # 14 days
}

resource "aws_sqs_queue" "incidents_queue" {
  name                       = "${local.name_prefix}-incidents-queue"
  visibility_timeout_seconds = 120    # 2 minutes for worker LLM processing
  message_retention_seconds  = 345600 # 4 days
  receive_wait_time_seconds  = 20     # Long polling enabled

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.incidents_dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_sqs_queue_policy" "incidents_queue_policy" {
  queue_url = aws_sqs_queue.incidents_queue.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowEventBridgePublish"
        Effect = "Allow"
        Principal = {
          Service = "events.amazonaws.com"
        }
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.incidents_queue.arn
      }
    ]
  })
}
