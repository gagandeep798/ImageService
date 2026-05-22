# Runbook: GDPR Erasure Request

**Trigger**: User submits right-to-erasure request (Article 17 GDPR)
**SLA**: Complete within 30 days of request

## Via API (self-service)
The user calls `DELETE /users/{user_id}` with their own JWT. The handler cascades deletion automatically.

## Via Operator CLI (out-of-band request)
```bash
# Dry-run first — shows what will be deleted
python scripts/gdpr_erase_user.py --user-id usr_abc --env prod --dry-run

# Execute (requires confirmation prompt)
python scripts/gdpr_erase_user.py --user-id usr_abc --env prod
```

## Verification
```bash
# Confirm user record is marked DELETED
aws dynamodb get-item \
  --table-name image-service-users-prod \
  --key '{"PK":{"S":"USER#usr_abc"},"SK":{"S":"PROFILE"}}' \
  --query 'Item.{status:status.S,gdpr_erased_at:gdpr_erased_at.S}'
```

## Important Notes
- S3 objects are deleted asynchronously via DynamoDB Streams TTL trigger (within 7 days)
- CloudTrail audit log of the erasure is retained for legal compliance (up to 7 years) — this is permissible under GDPR Art. 17(3)(b)
- The erasure log itself does NOT contain personal data — only `user_id` (a system identifier) and timestamps
