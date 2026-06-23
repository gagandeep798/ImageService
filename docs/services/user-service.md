# User Service

Manages user profiles, storage quotas, and GDPR erasure. Email addresses are never stored in plaintext.

## PII Handling

Email is hashed using **Argon2id** with a per-record random salt and a server-side pepper before being written to DynamoDB.

```
stored_hash = Argon2id( pepper + email.lower() , salt )
```

| Component | Where it lives | Purpose |
|-----------|---------------|---------|
| `email_hash` | DynamoDB `email_hash` field | Stored Argon2id output (base64) |
| `email_salt` | DynamoDB `email_salt` field | Per-record random 32 bytes (base64) |
| `pepper` | AWS Secrets Manager `image-service/{env}/pii_pepper` | Server-side secret prepended before hashing |

To verify an email during login: re-hash the candidate with the stored salt + pepper and compare using `hmac.compare_digest` (constant-time, prevents timing attacks).

The pepper is loaded once at Lambda cold-start via `get_settings()`. Changing the pepper invalidates all stored hashes and requires a full re-hash migration.

## Storage Quota

Each user has `storage_used_bytes` and `storage_quota_bytes` in their DynamoDB record.

**Enforcement** uses a DynamoDB conditional `UpdateItem` at upload initiation:

```
storage_used_bytes + upload_size <= storage_quota_bytes  AND  status = ACTIVE
```

This is atomic — concurrent uploads cannot both succeed if together they would exceed the quota.

**Default quota**: 10 GB (`10 * 1024 * 1024 * 1024` bytes).

To raise a user's quota:
```bash
aws dynamodb update-item \
  --table-name image-service-users-prod \
  --key '{"PK":{"S":"USER#<user_id>"},"SK":{"S":"PROFILE"}}' \
  --update-expression "SET storage_quota_bytes = :q" \
  --expression-attribute-values '{":q":{"N":"107374182400"}}'
```

**Quota lifecycle**:
- Reserved at `upload_initiate` (even before the file is uploaded to S3)
- `image_count` incremented at `finalize_upload` (when the file is confirmed in S3)
- Released at `upload_abort` or image soft-delete

## DynamoDB Schema

**Table**: `image-service-users-{env}`

**Primary key**: `PK = USER#<user_id>`, `SK = PROFILE`

**GSI**: `EmailHashIndex` — `PK = EMAILHASH#<email_hash>`, projection `KEYS_ONLY`
Used for email-based user lookup without exposing plaintext email as a key.

| Attribute | Type | Notes |
|-----------|------|-------|
| `user_id` | String | System identifier (ULID-based) |
| `display_name` | String | User-chosen public handle |
| `email_hash` | String | Argon2id hash (base64) |
| `email_salt` | String | Per-record salt (base64) |
| `EmailHashIndex_PK` | String | `EMAILHASH#<email_hash>` — GSI partition key |
| `status` | String | `ACTIVE`, `SUSPENDED`, `DELETED` |
| `storage_used_bytes` | Number | Atomically managed |
| `storage_quota_bytes` | Number | Default 10 GB |
| `image_count` | Number | Atomically managed |
| `created_at` | String | ISO 8601 |
| `updated_at` | String | ISO 8601 |
| `deleted_at` | String | Set on soft-delete or GDPR erasure |
| `gdpr_erased_at` | String | Set by GDPR erasure handler |
| `ttl` | Number | Unix epoch; set to `now + 90 days` on GDPR erasure |

## GDPR Erasure

`DELETE /users/{user_id}` triggers a cascade:

1. Paginate all images owned by the user via `UserImagesIndex`
2. Soft-delete each image (sets `status = DELETED`, `ttl = now + 7 days`)
3. Mark user record: `status = DELETED`, `gdpr_erased_at`, `ttl = now + 90 days`
4. S3 objects are removed asynchronously after the DynamoDB TTL fires

The erasure event is logged to CloudTrail. The log contains only `user_id` (a system identifier) and timestamps — no personal data.

For out-of-band erasure requests see [GDPR Erasure activity](../activities/gdpr-erasure.md).

## Handler

| Handler | File |
|---------|------|
| GDPR delete | [src/handlers/gdpr_delete_user.py](../../src/handlers/gdpr_delete_user.py) |

## Repository

[src/repositories/user_repository.py](../../src/repositories/user_repository.py)
