# Runbook: Lambda Errors

**Alarm**: `image-service-{function}-Errors-{env}`
**Severity**: WARNING / CRITICAL (depending on error rate)

## Diagnosis
```bash
# Recent errors
aws logs filter-log-events \
  --log-group-name /aws/lambda/image-service-{function}-{env} \
  --filter-pattern '"level":"ERROR"' \
  --start-time $(date -u -v-15M +%s000)
```

Check X-Ray for slow/failing traces:
```bash
aws xray get-service-graph \
  --start-time $(date -u -v-15M +%s) \
  --end-time $(date -u +%s)
```

## Post-Deploy Errors
If errors started immediately after a deploy:
1. Check if a migration is missing — run `make migrate-{env}`
2. Check if a Secrets Manager secret is missing for the new env var
3. Roll back: `sam deploy --config-env {env}` with the previous git SHA

## Cold Start Errors
If errors correlate with cold starts:
- Check Secrets Manager reachability from the Lambda VPC (VPC endpoint required)
- Check `SECRETSMANAGER_ENDPOINT_URL` env var if local

## Resolution
Fix the root cause and redeploy. For transient errors (network blip), the Lambda will retry automatically on the next invocation.
