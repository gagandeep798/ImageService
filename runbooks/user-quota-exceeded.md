# Runbook: User Quota Exceeded

**Alarm**: `quota.exceeded_errors > 100/5min`
**Severity**: WARNING

## What this means
A high volume of users are hitting their storage quota limit. This may indicate:
- A specific user or set of users hitting the limit repeatedly (possible abuse)
- The default quota is too low for the user tier

## Diagnosis
Query Athena for users hitting quota errors:
```sql
SELECT user_id, COUNT(*) AS error_count
FROM image_service_lambda_logs
WHERE message LIKE '%QUOTA_EXCEEDED%'
  AND year = YEAR(CURRENT_DATE)
  AND month = MONTH(CURRENT_DATE)
GROUP BY user_id
ORDER BY error_count DESC
LIMIT 20;
```

## Resolution — Increase quota for a specific user
```bash
aws dynamodb update-item \
  --table-name image-service-users-prod \
  --key '{"PK":{"S":"USER#usr_abc"},"SK":{"S":"PROFILE"}}' \
  --update-expression "SET storage_quota_bytes = :q" \
  --expression-attribute-values '{":q":{"N":"107374182400"}}'  # 100 GB
```

## Resolution — Abuse prevention
If the same user is uploading and immediately deleting to cycle quota:
1. Set user `status = SUSPENDED` via DynamoDB console
2. Investigate upload patterns via CloudTrail
3. Apply WAF rule to block the user's IP or Cognito sub if needed
