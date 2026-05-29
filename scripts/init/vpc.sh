#!/usr/bin/env bash
set -euo pipefail

ENDPOINT="http://localhost:4566"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"

log() { echo "[init:vpc] $*"; }

# ── VPC ───────────────────────────────────────────────────────────────────────
VPC_ID=$(aws --endpoint-url="$ENDPOINT" ec2 create-vpc \
    --cidr-block 10.0.0.0/16 \
    --region "$REGION" \
    --query 'Vpc.VpcId' --output text 2>/dev/null || echo "")

if [ -z "$VPC_ID" ]; then
    log "VPC already exists or could not be created — skipping"
    exit 0
fi

aws --endpoint-url="$ENDPOINT" ec2 create-tags \
    --resources "$VPC_ID" \
    --tags Key=Name,Value=image-service-vpc \
    --region "$REGION" 2>/dev/null || true

log "VPC: $VPC_ID"

# ── Subnets ───────────────────────────────────────────────────────────────────
create_subnet() {
    local cidr="$1" az="$2" name="$3"
    local id
    id=$(aws --endpoint-url="$ENDPOINT" ec2 create-subnet \
        --vpc-id "$VPC_ID" \
        --cidr-block "$cidr" \
        --availability-zone "${REGION}${az}" \
        --region "$REGION" \
        --query 'Subnet.SubnetId' --output text 2>/dev/null || echo "")
    if [ -n "$id" ]; then
        aws --endpoint-url="$ENDPOINT" ec2 create-tags \
            --resources "$id" \
            --tags Key=Name,Value="$name" \
            --region "$REGION" 2>/dev/null || true
        log "subnet: $name ($id)"
    fi
}

create_subnet 10.0.1.0/24  a image-service-public-1a
create_subnet 10.0.2.0/24  b image-service-public-1b
create_subnet 10.0.11.0/24 a image-service-private-1a
create_subnet 10.0.12.0/24 b image-service-private-1b

log "subnets ready"

# ── Security Groups ───────────────────────────────────────────────────────────
create_sg() {
    local name="$1" desc="$2"
    local id
    id=$(aws --endpoint-url="$ENDPOINT" ec2 create-security-group \
        --group-name "$name" \
        --description "$desc" \
        --vpc-id "$VPC_ID" \
        --region "$REGION" \
        --query 'GroupId' --output text 2>/dev/null || echo "")
    echo "$id"
}

# Lambda SG — egress-only (outbound to AWS service endpoints)
LAMBDA_SG=$(create_sg "image-service-lambda-sg" "Lambda functions — egress only")
if [ -n "$LAMBDA_SG" ]; then
    aws --endpoint-url="$ENDPOINT" ec2 authorize-security-group-egress \
        --group-id "$LAMBDA_SG" \
        --protocol -1 \
        --cidr 0.0.0.0/0 \
        --region "$REGION" 2>/dev/null || true
    log "sg: image-service-lambda-sg ($LAMBDA_SG)"
fi

# API Gateway SG — ingress HTTPS from internet
API_GW_SG=$(create_sg "image-service-api-gw-sg" "API Gateway — ingress 443")
if [ -n "$API_GW_SG" ]; then
    aws --endpoint-url="$ENDPOINT" ec2 authorize-security-group-ingress \
        --group-id "$API_GW_SG" \
        --protocol tcp \
        --port 443 \
        --cidr 0.0.0.0/0 \
        --region "$REGION" 2>/dev/null || true
    log "sg: image-service-api-gw-sg ($API_GW_SG)"
fi

# Secrets Manager VPC endpoint SG — ingress 443 from Lambda SG
SM_ENDPOINT_SG=$(create_sg "image-service-secretsmanager-endpoint-sg" "Secrets Manager VPC endpoint")
if [ -n "$SM_ENDPOINT_SG" ] && [ -n "$LAMBDA_SG" ]; then
    aws --endpoint-url="$ENDPOINT" ec2 authorize-security-group-ingress \
        --group-id "$SM_ENDPOINT_SG" \
        --protocol tcp \
        --port 443 \
        --source-group "$LAMBDA_SG" \
        --region "$REGION" 2>/dev/null || true
    log "sg: image-service-secretsmanager-endpoint-sg ($SM_ENDPOINT_SG)"
fi

# SQS VPC endpoint SG — ingress 443 from Lambda SG
SQS_ENDPOINT_SG=$(create_sg "image-service-sqs-endpoint-sg" "SQS VPC endpoint")
if [ -n "$SQS_ENDPOINT_SG" ] && [ -n "$LAMBDA_SG" ]; then
    aws --endpoint-url="$ENDPOINT" ec2 authorize-security-group-ingress \
        --group-id "$SQS_ENDPOINT_SG" \
        --protocol tcp \
        --port 443 \
        --source-group "$LAMBDA_SG" \
        --region "$REGION" 2>/dev/null || true
    log "sg: image-service-sqs-endpoint-sg ($SQS_ENDPOINT_SG)"
fi

log "security groups ready"
