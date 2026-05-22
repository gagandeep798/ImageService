# Runbook: DLQ Has Messages

**Alarm**: `image-service-FinalizeDLQ-{env}` or `image-service-ScanDLQ-{env}`
**Severity**: CRITICAL

## What this means
Messages reached the dead-letter queue after 3 failed processing attempts. Images may be stuck in PENDING_FINALIZE or SCANNING status.

## Diagnosis
```bash
# Count messages
aws sqs get-queue-attributes \
  --queue-url <DLQ_URL> \
  --attribute-names ApproximateNumberOfMessages

# Inspect a message
aws sqs receive-message --queue-url <DLQ_URL> --max-number-of-messages 1
```

Check CloudWatch Logs for the failed Lambda:
```
/aws/lambda/image-service-finalize-upload-{env}
```
Filter for `ERROR` log level within the alarm timeframe.

## Resolution
1. Fix the root cause (see error in logs — common causes: S3 key mismatch, DynamoDB permission error, Pillow parse failure on corrupt image)
2. Redrive messages back to the main queue:
```bash
aws sqs start-message-move-task \
  --source-arn <DLQ_ARN> \
  --destination-arn <MAIN_QUEUE_ARN>
```
3. Monitor the main queue to confirm messages are processed successfully

## Escalation
If redrive fails 3 more times, the image is irrecoverably stuck. Manually set status to ABORTED via the DynamoDB console and notify the user.
