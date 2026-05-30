#!/usr/bin/env bash
# Deploy finalize/scan/thumbnail pipeline functions to LocalStack Lambda and
# wire the S3 originals-bucket notification.
#
# Must run AFTER sam build — requires .aws-sam/build/ to exist.
# Called by: make deploy-pipeline-local
set -euo pipefail

ENDPOINT="http://localhost:4566"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
ACCOUNT="${LOCALSTACK_ACCOUNT_ID:-000000000000}"
BUILD_DIR="${PWD}/.aws-sam/build"
# Endpoint used by Lambda containers — on the Docker network, not the host
DOCKER_ENDPOINT="http://image-service-localstack:4566"

ORIGINALS_BUCKET="image-service-originals-${ACCOUNT}-${REGION}"
FINALIZE_NAME="image-service-finalize-upload-local"
SCAN_NAME="image-service-scan-complete-local"
THUMBNAILS_NAME="image-service-generate-thumbnails-local"
FINALIZE_ARN="arn:aws:lambda:${REGION}:${ACCOUNT}:function:${FINALIZE_NAME}"
SCAN_ARN="arn:aws:lambda:${REGION}:${ACCOUNT}:function:${SCAN_NAME}"
THUMBNAILS_ARN="arn:aws:lambda:${REGION}:${ACCOUNT}:function:${THUMBNAILS_NAME}"

log() { echo "[deploy-pipeline] $*"; }

aws_lambda() { aws --endpoint-url="${ENDPOINT}" --region="${REGION}" lambda "$@"; }
aws_s3api() { aws --endpoint-url="${ENDPOINT}" --region="${REGION}" s3api "$@"; }

deploy_or_update() {
    local name="$1" build_name="$2" handler="$3" env_json="$4"
    local zip="/tmp/${name}.zip"

    log "packaging ${name}..."
    (cd "${BUILD_DIR}/${build_name}" && zip -r "${zip}" . -q)

    if aws_lambda get-function --function-name "${name}" &>/dev/null; then
        aws_lambda update-function-code \
            --function-name "${name}" \
            --zip-file "fileb://${zip}" >/dev/null
        # wait for code update before changing config
        aws_lambda wait function-updated --function-name "${name}" 2>/dev/null || true
        aws_lambda update-function-configuration \
            --function-name "${name}" \
            --environment "{\"Variables\":${env_json}}" >/dev/null
        log "updated: ${name}"
    else
        aws_lambda create-function \
            --function-name "${name}" \
            --runtime python3.12 \
            --handler "${handler}" \
            --zip-file "fileb://${zip}" \
            --role "arn:aws:iam::${ACCOUNT}:role/lambda-role" \
            --timeout 60 \
            --memory-size 1024 \
            --environment "{\"Variables\":${env_json}}" >/dev/null
        log "created: ${name}"
    fi
}

# Env vars injected into every pipeline function
BASE='"AWS_ENDPOINT_URL":"'"${DOCKER_ENDPOINT}"'","AWS_DEFAULT_REGION":"'"${REGION}"'","ENV":"local","LOG_LEVEL":"INFO","POWERTOOLS_SERVICE_NAME":"image-service","POWERTOOLS_LOG_LEVEL":"INFO","IMAGES_TABLE_NAME":"image-service-images","USERS_TABLE_NAME":"image-service-users","ORIGINALS_BUCKET":"'"${ORIGINALS_BUCKET}"'","THUMBNAILS_BUCKET":"image-service-thumbnails-'"${ACCOUNT}"'-'"${REGION}"'","QUARANTINE_BUCKET":"image-service-quarantine-'"${ACCOUNT}"'-'"${REGION}"'","DYNAMO_GSI2_SHARD_COUNT":"8","PII_PEPPER":"'"${PII_PEPPER:-dev}"'"'

deploy_or_update "${FINALIZE_NAME}"   "FinalizeUploadFunction"   "src.handlers.finalize_upload.handler"   '{'"${BASE}"',"SCAN_COMPLETE_FUNCTION_ARN":"'"${SCAN_ARN}"'"}'
deploy_or_update "${SCAN_NAME}"       "ScanCompleteFunction"     "src.handlers.scan_complete.handler"     '{'"${BASE}"',"GENERATE_THUMBNAILS_FUNCTION_ARN":"'"${THUMBNAILS_ARN}"'"}'
deploy_or_update "${THUMBNAILS_NAME}" "GenerateThumbnailsFunction" "src.handlers.generate_thumbnails.handler" '{'"${BASE}"'}'

# Grant S3 permission to invoke FinalizeUploadFunction
aws_lambda add-permission \
    --function-name "${FINALIZE_NAME}" \
    --statement-id "s3-originals-invoke" \
    --action "lambda:InvokeFunction" \
    --principal "s3.amazonaws.com" \
    --source-arn "arn:aws:s3:::${ORIGINALS_BUCKET}" 2>/dev/null || true
log "lambda permission set: s3 → ${FINALIZE_NAME}"

# Wire S3 → FinalizeUploadFunction notification
aws_s3api put-bucket-notification-configuration \
    --bucket "${ORIGINALS_BUCKET}" \
    --notification-configuration '{
        "LambdaFunctionConfigurations": [{
            "LambdaFunctionArn": "'"${FINALIZE_ARN}"'",
            "Events": ["s3:ObjectCreated:*"],
            "Filter": {
                "Key": {
                    "FilterRules": [{"Name": "prefix", "Value": "originals/"}]
                }
            }
        }]
    }'
log "S3 notification wired: ${ORIGINALS_BUCKET} → ${FINALIZE_NAME}"

log "Pipeline ready — finalize → scan → thumbnails"
