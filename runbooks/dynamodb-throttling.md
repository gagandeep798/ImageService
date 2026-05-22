# Runbook: DynamoDB Throttling

**Alarm**: `image-service-dynamodb-connection-errors-{env}`
**Severity**: CRITICAL

## Diagnosis
```bash
# Check throttled requests
aws cloudwatch get-metric-statistics \
  --namespace AWS/DynamoDB \
  --metric-name ThrottledRequests \
  --dimensions Name=TableName,Value=image-service-images-{env} \
  --start-time $(date -u -v-30M +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 --statistics Sum

# Check consumed capacity
aws cloudwatch get-metric-statistics \
  --namespace AWS/DynamoDB \
  --metric-name ConsumedWriteCapacityUnits \
  --dimensions Name=TableName,Value=image-service-images-{env} \
  --start-time $(date -u -v-30M +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 --statistics Sum
```

## Common Causes
1. **Hot partition** — many writes to the same GSI2PK shard. Check if `SHARD_COUNT` needs increasing.
2. **Burst upload** — large number of concurrent uploads. Lambda concurrency spike.
3. **Table in UPDATING state** — GSI creation in progress limits capacity.

## Resolution
- PAY_PER_REQUEST tables auto-scale — throttling should resolve within minutes
- If sustained: check X-Ray traces to identify which operation is throttled
- For a hot partition: increase `DYNAMO_GSI2_SHARD_COUNT` env var and deploy (requires migration `0003` re-run is NOT needed — shard count change takes effect immediately for new writes)

## Prevention
Ensure `DYNAMO_GSI2_SHARD_COUNT` is set appropriately for traffic volume. At 1000 uploads/sec, use at least 16 shards.
