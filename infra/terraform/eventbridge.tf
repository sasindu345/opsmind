resource "aws_cloudwatch_event_bus" "opsmind_bus" {
  name = "${local.name_prefix}-bus"
}

# Rule 1: Forward CloudWatch Alarm State Changes to OpsMind SQS
resource "aws_cloudwatch_event_rule" "cloudwatch_alarms_rule" {
  name           = "${local.name_prefix}-cloudwatch-alarms"
  description    = "Route CloudWatch Alarm state changes to OpsMind queue"
  event_bus_name = aws_cloudwatch_event_bus.opsmind_bus.name

  event_pattern = jsonencode({
    source      = ["aws.cloudwatch"]
    detail-type = ["CloudWatch Alarm State Change"]
  })
}

resource "aws_cloudwatch_event_target" "sqs_alarm_target" {
  rule           = aws_cloudwatch_event_rule.cloudwatch_alarms_rule.name
  event_bus_name = aws_cloudwatch_event_bus.opsmind_bus.name
  target_id      = "OpsMindSQSAlarmTarget"
  arn            = aws_sqs_queue.incidents_queue.arn
}

# Rule 2: Forward Custom OpsMind Application Telemetry
resource "aws_cloudwatch_event_rule" "app_telemetry_rule" {
  name           = "${local.name_prefix}-app-telemetry"
  description    = "Route custom OpsMind telemetry events to queue"
  event_bus_name = aws_cloudwatch_event_bus.opsmind_bus.name

  event_pattern = jsonencode({
    source = ["opsmind"]
  })
}

resource "aws_cloudwatch_event_target" "sqs_telemetry_target" {
  rule           = aws_cloudwatch_event_rule.app_telemetry_rule.name
  event_bus_name = aws_cloudwatch_event_bus.opsmind_bus.name
  target_id      = "OpsMindSQSTelemetryTarget"
  arn            = aws_sqs_queue.incidents_queue.arn
}
