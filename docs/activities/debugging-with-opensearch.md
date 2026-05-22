# Debugging with OpenSearch

Live logs are indexed in OpenSearch within seconds of being emitted. This is the fastest way to debug a specific request or trace an image through the pipeline.

## Accessing Dashboards

| Environment | URL |
|-------------|-----|
| Local | `http://localhost:8080/dashboards/` (or `make dashboards-open`) |
| Prod | OpenSearch Dashboards VPC endpoint (ask an admin for the URL) |

## Index Pattern

Create the index pattern `image-service-*` in Dashboards to search across all daily indices.

Indices are named `image-service-lambda-logs-YYYY.MM.DD`. Data older than 14 days is deleted from OpenSearch — use [Athena](#athena-for-older-logs) for historical queries.

---

## Common Queries (Dashboards / Dev Tools)

### All errors in the last 15 minutes

```json
GET image-service-*/_search
{
  "query": {
    "bool": {
      "must": [
        {"term": {"level": "ERROR"}},
        {"range": {"timestamp": {"gte": "now-15m"}}}
      ]
    }
  },
  "sort": [{"timestamp": "desc"}],
  "size": 50
}
```

### Trace all events for a specific image

```json
GET image-service-*/_search
{
  "query": {"term": {"image_id": "img_01HZ..."}},
  "sort": [{"timestamp": "asc"}]
}
```

This shows the full journey: `upload_initiated` → `upload_finalized` → `image_activated` → (optional) `image_deleted`.

### All failed uploads by user in the last hour

```json
GET image-service-*/_search
{
  "query": {
    "bool": {
      "must": [
        {"term": {"user_id": "usr_abc"}},
        {"term": {"level": "ERROR"}},
        {"match": {"function_name": "upload"}},
        {"range": {"timestamp": {"gte": "now-1h"}}}
      ]
    }
  }
}
```

### Slow requests (duration > 3 seconds)

```json
GET image-service-*/_search
{
  "query": {
    "range": {"duration_ms": {"gte": 3000}}
  },
  "sort": [{"duration_ms": "desc"}],
  "size": 20
}
```

### DLQ messages — find the failed image

When a DLQ alarm fires, find the affected `image_id` via the `function_name`:

```json
GET image-service-*/_search
{
  "query": {
    "bool": {
      "must": [
        {"term": {"function_name": "image-service-finalize-upload-prod"}},
        {"term": {"level": "ERROR"}}
      ],
      "filter": {"range": {"timestamp": {"gte": "now-2h"}}}
    }
  }
}
```

### Deploy correlation — errors after a deploy

Find the deploy event then look for errors after it:

```json
GET cicd-logs-*/_search
{
  "query": {
    "bool": {
      "must": [
        {"term": {"event": "deploy_completed"}},
        {"term": {"env": "prod"}}
      ]
    }
  },
  "sort": [{"timestamp": "desc"}],
  "size": 5
}
```

Then query `image-service-*` with `"range": {"timestamp": {"gte": "<deploy_completed timestamp>"}}`.

---

## S3 Access Logs

S3 access logs are indexed in `image-service-s3-access-logs-YYYY.MM.DD`. To find all accesses to a specific image object:

```json
GET image-service-s3-access-logs-*/_search
{
  "query": {
    "match": {"message": "img_01HZ..."}
  },
  "sort": [{"timestamp": "desc"}]
}
```

---

## Log Fields Reference

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | date | ISO 8601 UTC |
| `level` | keyword | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `service` | keyword | Always `image-service` |
| `function_name` | keyword | Lambda function name |
| `request_id` | keyword | API Gateway request ID |
| `user_id` | keyword | Caller identity from JWT |
| `image_id` | keyword | Image being operated on |
| `message` | text | Human-readable event name |
| `duration_ms` | float | Handler wall-clock time |
| `cold_start` | boolean | Whether this was a cold start |
| `error` | text | Exception message (ERROR level only) |

**Note**: `email` and other PII fields are redacted to `[REDACTED]` by the log shipper before indexing.

---

## Athena for Older Logs

Logs older than 14 days are deleted from OpenSearch. For historical analysis use Athena:

```sql
-- Slow uploads over the last 30 days
SELECT DATE_TRUNC('day', from_iso8601_timestamp(timestamp)) AS day,
       APPROX_PERCENTILE(duration_ms, 0.99) AS p99_ms,
       COUNT(*) AS total
FROM image_service_lambda_logs
WHERE function_name LIKE '%upload%'
  AND year >= 2026
GROUP BY 1
ORDER BY 1 DESC;
```

Open the Athena console and select workgroup `image-service-analysis-prod`.

---

## Local Dev Tips

In local development, logs are only in OpenSearch if the `log_shipper` Lambda is running. For `sam local`, check the SAM terminal output directly — all Lambda logs are printed to stdout.

To check if a log event made it into local OpenSearch:

```bash
curl -s "http://localhost:8080/opensearch/image-service-*/_count" | python3 -m json.tool
```
