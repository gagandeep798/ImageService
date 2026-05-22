# Runbook: S3 Replication Lag

**Alarm**: S3 `ReplicationLatency` > 300s
**Severity**: WARNING

## Diagnosis
```bash
# Check replication metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/S3 \
  --metric-name ReplicationLatency \
  --dimensions Name=SourceBucket,Value=image-service-originals-{account}-{region}-prod \
               Name=DestinationBucket,Value=image-service-originals-{account}-us-west-2-prod \
               Name=RuleId,Value=replication-rule \
  --start-time $(date -u -v-1H +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 300 --statistics Maximum

# Check replication status on a specific object
aws s3api head-object \
  --bucket image-service-originals-{account}-{region}-prod \
  --key originals/{user_id}/... \
  --query 'ReplicationStatus'
```

## Common Causes
- Source region outage or S3 service event
- Destination region capacity constraints
- Very large object (> 1 GB) — normal replication latency

## Resolution
Replication lag is usually transient — monitor for 30 minutes before escalating.
If lag exceeds 1 hour: open AWS support ticket with the source bucket name and affected time range.

## Impact
During replication lag, objects are available in the source region. The service remains fully functional. Impact is only to the cross-region DR objective (RPO).
