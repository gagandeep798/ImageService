# Observability

The service uses a layered observability stack: structured logs for debugging, distributed traces for latency, custom metrics for alerting, and long-term log storage for compliance and historical analysis.

## Structured Logging

Every Lambda function is decorated with `@logger.inject_lambda_context` from AWS Lambda Powertools. All log lines are JSON with a consistent set of fields:

```json
{
  "timestamp": "2026-05-21T10:00:00.000Z",
  "level": "INFO",
  "service": "image-service",
  "function_name": "image-service-upload-initiate-prod",
  "request_id": "abc-123",
  "user_id": "usr_01HZ...",
  "image_id": "img_01HZ...",
  "message": "upload_initiated",
  "duration_ms": 45.2,
  "cold_start": false
}
```

**Sensitive fields** (`email`, `password`, `token`, `authorization`) are redacted to `[REDACTED]` by the log shipper before indexing in OpenSearch.

**Log groups**: `/aws/lambda/image-service-<function>-<env>`

**Retention**: 30 days (prod), 7 days (staging), 3 days (dev).

---

## Distributed Tracing (X-Ray)

All handlers use `@tracer.capture_lambda_handler` and repository methods use `@tracer.capture_method`. This creates X-Ray sub-segments for every DynamoDB and S3 call, showing latency breakdowns in the X-Ray Service Map.

**Sampling**: 5% in prod, 100% in dev/staging.

---

## Custom Metrics (CloudWatch)

All metrics are in the `ImageService` namespace and emitted via Lambda Powertools `Metrics`.

| Metric | Unit | Description |
|--------|------|-------------|
| `upload.initiated` | Count | Upload session started |
| `upload.completed` | Count | Multipart upload finalised |
| `upload.failed` | Count | Any upload error |
| `image.finalized` | Count | Finalize Lambda processed successfully |
| `image.deleted` | Count | Soft delete applied |
| `scan.clean` | Count | Image passed AV scan |
| `scan.threat_detected` | Count | Threat found; image quarantined |
| `dynamodb.call_latency_ms` | Milliseconds | Per-operation DynamoDB latency |
| `dynamodb.connection_errors` | Count | DynamoDB client errors |
| `s3.presign_latency_ms` | Milliseconds | Presigned URL generation time |
| `secrets.unexpected_change` | Count | Secret hash mismatch detected |
| `quota.exceeded_errors` | Count | Upload quota rejections |

---

## CloudWatch Alarms

| Alarm | Threshold | Severity | Action |
|-------|-----------|----------|--------|
| `upload.failed > 10/min` | 10 per minute, 2 periods | Critical | SNS → PagerDuty |
| `dynamodb.connection_errors > 0` | Any error, 1 period | Critical | SNS → PagerDuty |
| `scan.threat_detected > 0` | Any, 1 period | Critical | SNS → PagerDuty |
| `FinalizeDLQ messages > 0` | Any visible message | Critical | SNS → PagerDuty |
| `secrets.unexpected_change > 0` | Any, 1 period | Critical | SNS → PagerDuty |
| `API 5xx rate > 1%` | 2-minute window | Critical | SNS → PagerDuty |
| `Lambda p99 duration > 5s` | 3 periods | Warning | SNS → email |
| `Lambda throttles > 10/5min` | — | Warning | Auto-scale Lambda + SNS |

A **composite alarm** `image-service-critical` is an OR of all Critical alarms above. PagerDuty is paged only on transitions to ALARM, not per-minute.

---

## Log Shipping Architecture

```
CloudWatch Logs → Subscription Filter → Kinesis Data Stream
                                              │
                                              ▼
                                    log_shipper Lambda
                                    (PII redaction, enrichment)
                                              │
                                              ▼
                                    OpenSearch  (14-day hot index)
                                              │
                                    ┌─────────┴─────────┐
                                    │                   │
                                Dashboards         Kinesis Firehose
                                (live debug)            │
                                                        ▼
                                                 S3 Logs Bucket
                                                 (long-term storage)
```

---

## OpenSearch (Live Logs)

**Endpoint (local)**: `http://localhost:8080/opensearch/`

**Dashboards (local)**: `http://localhost:8080/dashboards/`

**Index pattern**: `image-service-lambda-logs-YYYY.MM.DD`

**Index lifecycle**:
- Hot (0–3 days): full indexing, 1 replica
- Warm (3–14 days): compressed, 0 replicas
- Deleted after 14 days (older logs in S3 / Athena)

For common query examples see [Debugging with OpenSearch](../activities/debugging-with-opensearch.md).

---

## S3 Logs Bucket

**Bucket**: `image-service-logs-<account>-<region>-<env>`

All log types land in Hive-compatible partitions for Athena:

```
logs/lambda/{function_name}/year=YYYY/month=MM/day=DD/hour=HH/
logs/apigw/year=YYYY/month=MM/day=DD/hour=HH/
logs/s3-access/year=YYYY/month=MM/day=DD/
logs/cloudtrail/AWSLogs/<account>/CloudTrail/<region>/YYYY/MM/DD/
logs/waf/year=YYYY/month=MM/day=DD/hour=HH/
```

**Lifecycle policies** (prod):

| Log type | Transition to IA | Transition to Glacier | Expire |
|----------|------------------|-----------------------|--------|
| Lambda / API GW / WAF | 30 days | 90 days | 365 days |
| S3 access logs | 30 days | 90 days | 365 days |
| CloudTrail | 90 days | 180 days | 2555 days (7 years) |

---

## Athena

**Workgroup**: `image-service-analysis-<env>`

**Query result bucket**: `s3://image-service-logs-<account>-<region>-<env>/athena-results/`

**Data scanned limit**: 10 GB per query (cost guard).

Saved named queries are deployed via `template.yaml` as `AWS::Athena::NamedQuery`:

| Query | Description |
|-------|-------------|
| `slow_uploads` | p99 upload latency per day |
| `upload_errors_by_user` | Error frequency per user (abuse detection) |
| `scan_threat_timeline` | All QUARANTINE events |
| `s3_access_by_object` | S3 access log audit trail per object |
| `waf_blocked_ips` | Top IPs blocked by WAF |

---

## CloudTrail

Account-level trail with S3 data events on all buckets and management events for DynamoDB, Lambda, API Gateway, IAM, and Secrets Manager.

Logs are delivered to the `cloudtrail-logs` S3 bucket and retained for 7 years (compliance requirement).
