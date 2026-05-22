# Security

## Authentication

All API endpoints require a valid JWT issued by the Cognito User Pool, except `GET /health`.

**API Gateway JWT Authorizer** validates the token signature against the User Pool JWKS endpoint — no Lambda invocation needed for auth. Claims are forwarded in `event.requestContext.authorizer.jwt.claims`.

**Identity propagation**: `src/common/middleware.get_caller_user_id()` extracts `sub` from the JWT claims and rejects requests with no valid identity. The `user_id` field in request bodies is validated against the JWT `sub` — clients cannot upload on behalf of other users.

**Admin access**: Users in the `admin` Cognito group can delete any image and perform GDPR erasure for any user.

**Local dev bypass**: When running with `sam local`, pass `?_dev_user_id=usr_abc` as a query parameter to skip Cognito validation.

---

## Secrets Management

All credentials are stored in AWS Secrets Manager. Nothing sensitive is in environment variables, code, or committed files.

**Secret paths** (per environment):

| Path | Contents |
|------|----------|
| `image-service/{env}/dynamodb` | Table names, region, **DynamoDB role ARNs** |
| `image-service/{env}/s3` | Bucket names |
| `image-service/{env}/pii_pepper` | Argon2id pepper for email hashing |
| `image-service/{env}/cloudfront` | Private key PEM, key pair ID |
| `image-service/{env}/alerts` | Slack webhook, PagerDuty API key |

**Cold-start loading**: `src/common/config.get_settings()` is decorated with `@lru_cache` — Secrets Manager is called exactly once per Lambda container lifetime.

**Tamper detection**: The `backup_secrets` Lambda runs daily and computes `SHA-256(name:value)` for every secret. If a hash changes without a known rotation event, the `secrets.unexpected_change` metric fires and triggers a PagerDuty alert.

---

## PII Handling

Email addresses are hashed with **Argon2id** (time_cost=2, memory_cost=64 MB, parallelism=2) using a per-record salt plus a server-side pepper. Plaintext email is never written to DynamoDB.

See [User Service](user-service.md) for full details.

---

## Reverse Proxy (Nginx)

In local dev, Nginx is the only container that binds a host port. All upstream service ports are container-internal (`expose`, not `ports`).

Nginx configuration:
- `proxy_hide_header Server` — hides upstream identity
- Security headers on all responses: `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy`
- Custom 404/500 error pages — no stack traces or version strings in error responses
- Request routing by path prefix: `/api/` → LocalStack, `/opensearch/` → OpenSearch, `/dashboards/` → Dashboards

In production, API Gateway + CloudFront serve as the reverse proxy. Lambda has no public endpoint.

---

## WAF

`AWS::WAFv2::WebACL` is attached to the API Gateway stage.

| Rule | Action |
|------|--------|
| `AWS-AWSManagedRulesCommonRuleSet` | Block (OWASP top 10: SQLi, XSS, etc.) |
| `AWS-AWSManagedRulesKnownBadInputsRuleSet` | Block |
| `RateLimitRule` | Block after 100 requests per 5 minutes per IP |
| `LargeBodyRule` | Block requests with body > 10 KB (except `/images/{id}/parts`) |

WAF logs are delivered to CloudWatch Logs and shipped to S3 and OpenSearch via the log pipeline.

---

## VPC and Network Security

All Lambda functions run inside a VPC in private subnets across two availability zones.

**Security groups**:
- `sg-lambda-egress` — Lambda functions: outbound 443 to VPC endpoints only; no inbound
- AWS services (DynamoDB, S3, Secrets Manager, SQS) are accessed via **VPC Gateway / Interface Endpoints** — traffic never leaves the AWS backbone

**No public IPs** are assigned to any Lambda or compute resource.

---

## IAM — Least Privilege

Each Lambda function has a dedicated execution role. Example for `upload_initiate`:

```yaml
Policies:
  - dynamodb:PutItem on images table
  - dynamodb:UpdateItem on users table
  - s3:CreateMultipartUpload on originals bucket
  - secretsmanager:GetSecretValue on image-service/{env}/*
  - logs:CreateLogGroup, logs:CreateLogStream, logs:PutLogEvents
  - xray:PutTraceSegments, xray:PutTelemetryRecords
```

No function has `*` actions or cross-table write permissions beyond what its single operation requires.

---

## Content Validation

At `finalize_upload`:
- `Pillow.Image.open()` is called on the first 64 KB of the uploaded object. If it raises an exception, the file is not a valid image and the record is not advanced to SCANNING.
- File extension and declared `content_type` are validated at upload initiation. Allowed types: `image/jpeg`, `image/png`, `image/webp`, `image/gif`.

Virus/malware scanning runs in Stage 2 of the [Processing Pipeline](processing-pipeline.md).

---

## S3 Security

- All buckets: **public access blocked** at bucket and account level
- **Server-side encryption**: SSE-S3 (AES-256) on originals and thumbnails; SSE-KMS on quarantine bucket (separate key)
- **Versioning** enabled on originals and logs buckets
- **Presigned URL scoping**: upload part URLs are scoped to a specific `upload_id` and `part_number`
- **CORS** on the originals bucket is restricted to `PUT`, `GET`, `HEAD` methods only

---

## DynamoDB Three-Tier Access Control

DynamoDB access is split across three separate IAM roles. Each role is assumed via STS at Lambda cold-start (`src/common/dynamo.py`) and the resulting boto3 resource singleton is reused for the lifetime of the container.

| Tier | IAM Role | Permitted actions | Used by |
|------|----------|-------------------|---------|
| **Read** | `image-service-dynamo-read-{env}` | `GetItem`, `BatchGetItem`, `Query`, `Scan`, `DescribeTable` | All read operations in both repositories |
| **Write** | `image-service-dynamo-write-{env}` | `PutItem`, `UpdateItem`, `BatchWriteItem` (non-delete attributes) | `create_user`, `create_pending`, `record_part`, `set_status`, quota updates, thumbnail keys |
| **Delete** | `image-service-dynamo-delete-{env}` | `UpdateItem` restricted to `{status, deleted_at, gdpr_erased_at, ttl, GSI2PK, updated_at}` only | `soft_delete` (images), `soft_delete_user` (users), GDPR handler |

**Why three tiers instead of one Lambda execution role?**

A single execution role with `dynamodb:*` means a bug in any handler — including a dependency with a supply-chain compromise — can modify or delete any data. With separate roles:
- A bug in `upload_initiate` cannot soft-delete records (wrong role, wrong permitted attributes)
- A bug in `delete_image` cannot create new records or modify non-delete fields
- The delete role's `UpdateItem` condition expression limits which attributes can be set, enforced at the AWS API level — not just in application code

**Role ARN configuration**

Role ARNs are stored in the `image-service/{env}/dynamodb` Secrets Manager secret:

```json
{
  "images_table": "image-service-images-prod",
  "users_table": "image-service-users-prod",
  "read_role_arn": "arn:aws:iam::123456789012:role/image-service-dynamo-read-prod",
  "write_role_arn": "arn:aws:iam::123456789012:role/image-service-dynamo-write-prod",
  "delete_role_arn": "arn:aws:iam::123456789012:role/image-service-dynamo-delete-prod"
}
```

When role ARNs are empty (local dev, unit tests), `dynamo.py` falls back to the Lambda execution role / moto mock credentials without any STS call.

**Trust policy**

Each role's trust policy allows the Lambda execution role to assume it:

```json
{
  "Principal": {"AWS": "arn:aws:iam::<account>:root"},
  "Action": "sts:AssumeRole"
}
```

The `DynamoDBDeleteRole` and `DynamoDBWriteRole` are defined in `template.yaml` as `AWS::IAM::Role` resources. The Lambda execution role has `sts:AssumeRole` permission scoped to those specific role ARNs.
