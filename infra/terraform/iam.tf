resource "aws_iam_role" "opsmind_node_role" {
  name = "${local.name_prefix}-node-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_policy" "opsmind_least_privilege_policy" {
  name        = "${local.name_prefix}-least-privilege"
  description = "Scoped permissions for OpsMind worker and API (SQS, DynamoDB, S3, CloudWatch, Bedrock)."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # SQS Queue Operations
      {
        Sid    = "SQSQueuePermissions"
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:SendMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility"
        ]
        Resource = [
          aws_sqs_queue.incidents_queue.arn,
          aws_sqs_queue.incidents_dlq.arn
        ]
      },
      # DynamoDB Table Permissions
      {
        Sid    = "DynamoDBTablePermissions"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = [
          aws_dynamodb_table.incidents.arn,
          "${aws_dynamodb_table.incidents.arn}/index/*"
        ]
      },
      # S3 Artifacts Bucket Permissions
      {
        Sid    = "S3ArtifactsPermissions"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.artifacts.arn,
          "${aws_s3_bucket.artifacts.arn}/*"
        ]
      },
      # CloudWatch Metrics & Logs
      {
        Sid    = "CloudWatchObservability"
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricData",
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogStreams"
        ]
        Resource = "*"
      },
      # Bedrock LLM Invocations
      {
        Sid    = "BedrockModelInvocations"
        Effect = var.enable_bedrock ? "Allow" : "Deny"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = "arn:aws:bedrock:*::foundation-model/*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "opsmind_attach" {
  role       = aws_iam_role.opsmind_node_role.name
  policy_arn = aws_iam_policy.opsmind_least_privilege_policy.arn
}

resource "aws_iam_instance_profile" "opsmind_profile" {
  name = "${local.name_prefix}-instance-profile"
  role = aws_iam_role.opsmind_node_role.name
}
