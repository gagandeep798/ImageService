# Runbook: OpenSearch Log Query (Live Debugging)

**Access**: http://localhost:8080/dashboards/ (local) or the OpenSearch Dashboards URL in prod

## Common Queries

### All errors in last 15 minutes
```json
{
  "query": {
    "bool": {
      "must": [
        {"term": {"level": "ERROR"}},
        {"range": {"timestamp": {"gte": "now-15m"}}}
      ]
    }
  }
}
```

### Trace all events for an image
```json
{
  "query": {"term": {"image_id": "img_01HZ..."}}
}
```

### Failed uploads by user
```json
{
  "query": {
    "bool": {
      "must": [
        {"term": {"user_id": "usr_abc"}},
        {"term": {"message": "upload_failed"}}
      ]
    }
  }
}
```

## Index Pattern
`image-service-lambda-logs-*` — all Lambda logs
`image-service-s3-access-logs-*` — S3 access logs
`image-service-cicd-logs-*` — deploy events

## Data Retention
Hot (0–3 days): fast search
Warm (3–14 days): slower but queryable
For older data: use Athena queries against the S3 logs bucket

## Local Dev
After `make localstack-up`, OpenSearch Dashboards is available at http://localhost:8080/dashboards/
Create an index pattern `image-service-*` to start exploring logs.
