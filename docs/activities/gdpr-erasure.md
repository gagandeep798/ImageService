# GDPR Erasure

Covers the right to erasure under GDPR Article 17. The service supports both self-service erasure (user-initiated via the API) and operator-initiated erasure for out-of-band legal requests.

## SLA

Erasure must be completed within **30 days** of a verified request.

---

## Self-Service (API)

Users can erase their own data by calling:

```
DELETE /users/{user_id}
Authorization: Bearer <jwt>
```

The JWT `sub` must match `{user_id}`. Admins (Cognito group `admin`) can erase any user.

**What happens**:
1. All images owned by the user are soft-deleted (`status = DELETED`, `ttl = now + 7 days`)
2. The user record is marked `status = DELETED`, `gdpr_erased_at = now`, `ttl = now + 90 days`
3. S3 objects are deleted asynchronously after the 7-day TTL by the DynamoDB Streams cleanup Lambda
4. The erasure event is logged to CloudTrail (contains only `user_id` and timestamps — no personal data)

**Response**:
```json
{
  "data": {
    "user_id": "usr_abc",
    "erased_at": "2026-05-21T10:00:00Z",
    "images_deleted": 42
  }
}
```

---

## Operator CLI (Out-of-Band Requests)

For erasure requests received by email or through legal channels, use the operator script:

```bash
# Preview (dry run) — shows what will be deleted without making changes
python scripts/gdpr_erase_user.py --user-id usr_abc --env prod --dry-run

# Execute (prompts for confirmation)
python scripts/gdpr_erase_user.py --user-id usr_abc --env prod
# Erase all data for usr_abc in prod? [yes/N]: yes
```

The script requires `DYNAMODB_ENDPOINT_URL` to be unset (or set to the correct prod endpoint) and valid AWS credentials for the prod account.

---

## Verifying Erasure

Check the user record:

```bash
aws dynamodb get-item \
  --table-name image-service-users-prod \
  --key '{"PK":{"S":"USER#usr_abc"},"SK":{"S":"PROFILE"}}' \
  --query 'Item.{status:status.S,erased_at:gdpr_erased_at.S,ttl:ttl.N}'
```

Expected output:
```json
{"status": "DELETED", "erased_at": "2026-05-21T10:00:00Z", "ttl": "1761825600"}
```

Check that images are also deleted:

```bash
aws dynamodb query \
  --table-name image-service-images-prod \
  --index-name UserImagesIndex \
  --key-condition-expression "GSI1PK = :pk" \
  --expression-attribute-values '{":pk":{"S":"USER#usr_abc"}}' \
  --filter-expression "#s <> :deleted" \
  --expression-attribute-names '{"#s":"status"}' \
  --expression-attribute-values '{":pk":{"S":"USER#usr_abc"},":deleted":{"S":"DELETED"}}' \
  --query 'Count'
# Should return 0
```

---

## S3 Object Cleanup Timeline

S3 objects are **not** deleted synchronously at erasure time. The timeline:

| Day | Event |
|-----|-------|
| 0 | Erasure called; DynamoDB records soft-deleted with `ttl = now + 7 days` |
| 0–7 | Image metadata is not visible via API (`status = DELETED`) |
| 7 | DynamoDB TTL expires; Streams event fires → S3 cleanup Lambda deletes originals and thumbnails |
| 90 | User record TTL expires; DynamoDB removes the user item |

If S3 cleanup is needed urgently (e.g., the user uploaded sensitive content), trigger it manually:

```bash
# List objects for this user
aws s3 ls s3://image-service-originals-<account>-<region>-prod/originals/usr_abc/

# Delete all objects (irreversible)
aws s3 rm s3://image-service-originals-<account>-<region>-prod/originals/usr_abc/ --recursive
```

---

## Compliance Notes

- The erasure audit log in CloudTrail is retained for **7 years** (legal compliance). The log records *that* an erasure occurred, not the personal data that was erased.
- GDPR Article 17(3)(b) permits retention of records for legal obligations — the CloudTrail retention is covered by this exemption.
- The `gdpr_erased_at` timestamp on the user DynamoDB record provides a verifiable audit trail of when erasure was completed.
- Email is stored only as an Argon2id hash — there is no plaintext to erase beyond the hash itself, which becomes meaningless once the pepper is rotated.
