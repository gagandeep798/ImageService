# Incident Response

## Alert Routing

All CloudWatch alarms publish to SNS topic `image-service-alerts-{env}`.

- **Critical alarms** → PagerDuty (immediate page to on-call)
- **All alarms** → Slack channel (formatted message with runbook link)

The Slack message format:
```
🔴 image-service-FinalizeDLQ-prod transitioned to ALARM
ApproximateNumberOfMessagesVisible >= 1 for 1 datapoints within 1 minute
Runbook: runbooks/dlq-has-messages.md
```

The composite alarm `image-service-critical-{env}` is an OR of all Critical alarms. PagerDuty is paged only on the composite alarm to prevent alert storms.

---

## Runbook Index

| Alarm | Runbook | Severity |
|-------|---------|---------|
| `upload.failed > 10/min` | [DLQ Has Messages](../../runbooks/dlq-has-messages.md) | Critical |
| `FinalizeDLQ messages > 0` | [DLQ Has Messages](../../runbooks/dlq-has-messages.md) | Critical |
| `ScanDLQ messages > 0` | [DLQ Has Messages](../../runbooks/dlq-has-messages.md) | Critical |
| `dynamodb.connection_errors > 0` | [DynamoDB Throttling](../../runbooks/dynamodb-throttling.md) | Critical |
| `scan.threat_detected > 0` | [DLQ Has Messages](../../runbooks/dlq-has-messages.md) | Critical |
| `secrets.unexpected_change > 0` | [GDPR Erasure](../../runbooks/gdpr-erasure-request.md) | Critical |
| `API 5xx rate > 1%` | [Lambda Errors](../../runbooks/lambda-errors.md) | Critical |
| `Lambda errors > 0` | [Lambda Errors](../../runbooks/lambda-errors.md) | Warning |
| `Lambda throttles > 10/5min` | [DynamoDB Throttling](../../runbooks/dynamodb-throttling.md) | Warning |
| `DynamoDB p99 > 100ms` | [DynamoDB Throttling](../../runbooks/dynamodb-throttling.md) | Warning |
| `quota.exceeded_errors > 100/5min` | [User Quota](../../runbooks/user-quota-exceeded.md) | Warning |
| `S3 replication lag > 300s` | [S3 Replication](../../runbooks/s3-replication-lag.md) | Warning |
| `OpenSearch cluster red/yellow` | [OpenSearch Log Query](../../runbooks/opensearch-log-query.md) | Warning |

---

## Escalation Path

```
Slack alert (all severities)
      │
      ▼
On-call engineer acknowledges in PagerDuty (< 15 min SLA)
      │
      ▼
Follow runbook
      │
      ├── Resolved  → close PagerDuty incident, write post-mortem if > 30 min
      └── Escalate  → page senior engineer or AWS support
```

---

## First Steps for Any Alert

1. **Check the deploy log** in OpenSearch (`cicd-logs-*`) — did this start after a deploy?
2. **Check Lambda errors** in `/aws/lambda/image-service-*-{env}` CloudWatch logs
3. **Check X-Ray** service map for latency spikes or error clusters
4. **Check DynamoDB metrics** for throttling or elevated latency
5. **Check SQS DLQs** for stuck messages

---

## Post-Incident

For any incident lasting more than 30 minutes or causing user-visible impact:

1. Write a brief post-mortem in the team wiki covering: timeline, root cause, impact, and action items
2. Create a GitHub issue for each action item (preventive measure, runbook update, alert threshold change)
3. Update the relevant runbook if the diagnosis steps were unclear

---

## Useful Commands

```bash
# Check DLQ message count
aws sqs get-queue-attributes \
  --queue-url <DLQ_URL> \
  --attribute-names ApproximateNumberOfMessages

# Inspect a DLQ message
aws sqs receive-message --queue-url <DLQ_URL> --max-number-of-messages 1

# Redrive DLQ messages back to main queue
aws sqs start-message-move-task \
  --source-arn <DLQ_ARN> \
  --destination-arn <MAIN_QUEUE_ARN>

# Recent Lambda errors
aws logs filter-log-events \
  --log-group-name /aws/lambda/image-service-finalize-upload-prod \
  --filter-pattern '"level":"ERROR"' \
  --start-time $(date -u -v-30M +%s000)

# Check DynamoDB throttling
aws cloudwatch get-metric-statistics \
  --namespace AWS/DynamoDB \
  --metric-name ThrottledRequests \
  --dimensions Name=TableName,Value=image-service-images-prod \
  --start-time $(date -u -v-30M +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 --statistics Sum
```
