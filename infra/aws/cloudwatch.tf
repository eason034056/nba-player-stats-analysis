locals {
  ec2_recover_arn = "arn:aws:automate:${var.region}:ec2:recover"
  alarm_notify    = aws_sns_topic.alarms[*].arn
}

resource "aws_sns_topic" "alarms" {
  count = var.alarm_email == "" ? 0 : 1
  name  = "${local.name_prefix}-ec2-alarms"
}

resource "aws_sns_topic_subscription" "alarms_email" {
  count     = var.alarm_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alarms[0].arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

resource "aws_cloudwatch_metric_alarm" "system_status" {
  alarm_name          = "${local.name_prefix}-ec2-system-status"
  alarm_description   = "System status check failed. Recover the instance."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "StatusCheckFailed_System"
  namespace           = "AWS/EC2"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0

  dimensions = {
    InstanceId = aws_instance.app.id
  }

  alarm_actions = concat([local.ec2_recover_arn], local.alarm_notify)
}

resource "aws_cloudwatch_metric_alarm" "disk_used" {
  alarm_name          = "${local.name_prefix}-ec2-disk-used"
  alarm_description   = "Root volume used percent is at least 80."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2
  metric_name         = "disk_used_percent"
  namespace           = "CWAgent"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  treat_missing_data  = "notBreaching"

  dimensions = {
    InstanceId = aws_instance.app.id
  }

  alarm_actions = local.alarm_notify
}
