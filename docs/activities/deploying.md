# Deploying

## Pipeline Overview

```
Merge to main
      │
      ▼
GitHub Actions CI (ci.yml)
  lint → typecheck → unit tests → sam build → integration tests
      │
      ▼ (if CI passes)
GitHub Actions Deploy (deploy.yml)
  sam build
      │
      ▼
Deploy to Staging
  sam deploy --config-env staging
  python migrations/runner.py --env staging
  smoke test /health
      │
      ▼
Manual Approval Gate (GitHub Environment: production)
      │
      ▼
Deploy to Production
  sam deploy --config-env prod
  python migrations/runner.py --env prod
  smoke test /health
      │
      ▼
Deploy log written to CloudWatch + OpenSearch
```

---

## Environment Configuration

Environments are configured in `samconfig.toml`. Each environment deploys the same `template.yaml` with different `Env` parameter values, causing all resource names to be suffixed with the environment name.

| Environment | Account | Auto-deploy | Approval |
|-------------|---------|-------------|---------|
| `local` | — | `make start-api` | — |
| `dev` | dev AWS account | manual | none |
| `staging` | staging AWS account | on merge to main | none |
| `prod` | prod AWS account | on merge to main | manual (GitHub) |

---

## Manual Deploy

```bash
# Staging
make deploy-staging

# Production (prompts for 3s before proceeding)
make deploy-prod
```

Both targets run in order: `sam build` → `sam deploy` → `migrations` → done.

---

## Migrations at Deploy Time

Migrations always run **after** `sam deploy` and **before** the new Lambda code receives traffic. This ensures the schema that new code expects is in place before the first invocation.

If a migration fails, the deploy script exits non-zero and the CI pipeline fails — the old Lambda code continues running until the issue is resolved and the deploy is retried.

---

## Deploy Logs

Every deploy writes a structured log event to CloudWatch Logs group `/image-service/cicd/deploys` and to OpenSearch index `cicd-logs-YYYY.MM.DD`:

```json
{
  "event": "deploy_started",
  "env": "staging",
  "git_sha": "abc123",
  "triggered_by": "github-actions",
  "workflow_run_id": "12345678",
  "timestamp": "2026-05-21T10:00:00Z"
}
```

A `deploy_completed` event with `"status": "success"` or `"status": "failed"` is written at the end. This lets you correlate a deploy with any error rate change visible in the OpenSearch Dashboards.

---

## Rolling Back

SAM deploy uses CloudFormation changesets. To roll back to the previous version:

```bash
# Find the previous successful stack version
aws cloudformation describe-stack-events \
  --stack-name image-service-prod \
  --query 'StackEvents[?ResourceStatus==`UPDATE_COMPLETE`].[Timestamp,LogicalResourceId]'

# Roll back by deploying the previous git SHA
git checkout <previous_sha>
make deploy-prod
```

For a DynamoDB schema issue, use migration rollback:
```bash
python migrations/runner.py --env prod --rollback <migration_number>
```

---

## GitHub Secrets Required

| Secret | Used by |
|--------|---------|
| `STAGING_DEPLOY_ROLE_ARN` | OIDC role assumed by staging deploy job |
| `PROD_DEPLOY_ROLE_ARN` | OIDC role assumed by prod deploy job |

Both roles require `cloudformation:*`, `lambda:*`, `s3:*`, `iam:PassRole`, and `secretsmanager:GetSecretValue` on the relevant account.

---

## Smoke Tests

After each deploy the workflow calls:

```bash
API_URL=$(aws cloudformation describe-stacks \
  --stack-name image-service-{env} \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" \
  --output text)

STATUS=$(curl -sf "${API_URL}/health" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
test "$STATUS" = "healthy"
```

If the health check does not return `healthy`, the workflow fails and the prod deploy gate is not reached.
