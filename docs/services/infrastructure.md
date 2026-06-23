# Infrastructure

All infrastructure is defined in [template.yaml](../../template.yaml) as an AWS SAM application. A single parameterised template is deployed to dev, staging, and prod via `samconfig.toml`.

## DynamoDB Tables

### `image-service-images-{env}`

Billing mode: `PAY_PER_REQUEST`. PITR: enabled. TTL attribute: `ttl`. Streams: `NEW_AND_OLD_IMAGES`.

**Primary key**: `PK = IMG#<image_id>`, `SK = META#<image_id>`

**GSI — UserImagesIndex**

| Key | Value |
|-----|-------|
| Partition | `GSI1PK = USER#<user_id>` |
| Sort | `GSI1SK = <created_at_iso>#<image_id>` |
| Projection | ALL |

Enables time-sorted per-user listing.

**GSI — StatusIndex**

| Key | Value |
|-----|-------|
| Partition | `GSI2PK = STATUS#<status>#<shard>` |
| Sort | `GSI2SK = <created_at_iso>#<image_id>` |
| Projection | KEYS_ONLY + `{user_id, title, s3_key, content_type, size_bytes}` |

Enables global listing by status. The partition key is **write-sharded** to prevent hot partitions:

```python
shard = MD5(image_id) % DYNAMO_GSI2_SHARD_COUNT   # default 8 shards
GSI2PK = f"STATUS#{status}#{shard}"
```

Global list queries fan out across all shards in parallel (scatter-gather) and merge results by `created_at`.

---

### `image-service-users-{env}`

**Primary key**: `PK = USER#<user_id>`, `SK = PROFILE`

**GSI — EmailHashIndex**: `PK = EMAILHASH#<email_hash>`, projection `KEYS_ONLY`.

---

### `image-service-migrations-{env}`

Tracks applied DynamoDB migrations. See [Database Migrations](../activities/migrations.md).

---

### `image-service-secret-hashes-{env}`

Stores SHA-256 hashes of Secrets Manager values for daily tamper detection.

---

## S3 Buckets

| Bucket | Purpose | Encryption | Versioning |
|--------|---------|-----------|-----------|
| `originals-<acct>-<region>-<env>` | Raw uploads | SSE-S3 | Yes |
| `thumbnails-<acct>-<region>-<env>` | Generated variants | SSE-S3 | No |
| `quarantine-<acct>-<region>-<env>` | Threat-detected objects | SSE-KMS | No |
| `logs-<acct>-<region>-<env>` | All service logs | SSE-S3 | Yes |
| `cloudtrail-logs-<acct>-<region>-<env>` | CloudTrail delivery | SSE-S3 | No |
| `backups-<acct>-<region>-<env>` | DynamoDB exports | SSE-S3 | No |

**Originals lifecycle rules**:

| Rule | Trigger |
|------|---------|
| Transition to S3-IA | After 30 days |
| Transition to Glacier | After 180 days |
| Abort incomplete multipart uploads | After 7 days |
| Expire non-current versions | After 30 days |

---

## SQS Queues

| Queue | Visibility timeout | Max attempts | DLQ |
|-------|--------------------|--------------|-----|
| `FinalizeQueue` | 60 s | 3 | `FinalizeDLQ` |
| `ScanQueue` | 120 s | 3 | `ScanDLQ` |
| `ThumbnailQueue` | 120 s | — | — |

S3 sends `ObjectCreated` events to `FinalizeQueue` via an SQS bucket notification policy. An explicit `AWS::SQS::QueuePolicy` grants `s3.amazonaws.com` permission to `sqs:SendMessage` scoped to the originals bucket ARN.

---

## Lambda Functions

| Function | Trigger | Memory | Timeout | Reserved concurrency |
|----------|---------|--------|---------|---------------------|
| `upload_initiate` | API Gateway POST /images | 512 MB | 30 s | 50 |
| `upload_part` | API Gateway POST /images/{id}/parts | 512 MB | 30 s | — |
| `upload_complete` | API Gateway POST /images/{id}/complete | 512 MB | 30 s | — |
| `upload_abort` | API Gateway DELETE /images/{id}/upload | 512 MB | 30 s | — |
| `finalize_upload` | SQS FinalizeQueue | 1024 MB | 60 s | 100 |
| `scan_complete` | SQS ScanQueue | 512 MB | 30 s | — |
| `generate_thumbnails` | SQS ThumbnailQueue | 1024 MB | 120 s | — |
| `get_image` | API Gateway GET /images/{id} | 512 MB | 30 s | — |
| `list_images` | API Gateway GET /images | 512 MB | 30 s | — |
| `delete_image` | API Gateway DELETE /images/{id} | 512 MB | 30 s | — |
| `download` | API Gateway GET /images/{id}/download | 512 MB | 30 s | — |
| `health` | API Gateway GET /health | 512 MB | 30 s | — |
| `gdpr_delete_user` | API Gateway DELETE /users/{id} | 512 MB | 300 s | — |
| `log_shipper` | Kinesis | 256 MB | 30 s | — |
| `slack_notifier` | SNS | 256 MB | 30 s | — |
| `scale_lambda` | EventBridge (throttle alarm) | 256 MB | 30 s | — |
| `backup_secrets` | EventBridge (daily cron) | 256 MB | 120 s | — |

All functions run Python 3.12 on x86_64 with AWS Lambda Powertools pre-loaded via a Lambda Layer.

---

## API Gateway

- Type: `AWS::Serverless::Api` (REST, not HTTP API)
- Stage: `v1`
- JWT Authorizer: Cognito User Pool
- X-Ray tracing: enabled
- Throttle limits: 500 req/s steady, 1000 req/s burst
- Access logs: JSON format → CloudWatch Logs

---

## Kinesis

**`image-service-live-logs-{env}`**: 2 shards, 24-hour retention.

CloudWatch Logs subscription filters on all Lambda log groups publish to this stream. The `log_shipper` Lambda consumes it and bulk-indexes into OpenSearch.

---

## Cognito

`AWS::Cognito::UserPool` with email verification and strong password policy (12 chars, upper/lower/number/symbol). App client has no secret (SPA-compatible). Token validity: access 1 hour, refresh 30 days.

---

## CloudFront

Sits in front of the S3 originals bucket for downloads. Origin Access Control (OAC) restricts direct S3 access — only CloudFront can read originals. Download URLs are CloudFront signed URLs generated by the `download` Lambda using an RSA key pair stored in Secrets Manager.

---

## Environment Parameters

All resource names include the `{Env}` CloudFormation parameter so multiple environments can coexist in the same AWS account or be deployed to separate accounts.

```toml
# samconfig.toml
[prod.deploy.parameters]
parameter_overrides = "Env=prod LogLevel=WARNING"
```
