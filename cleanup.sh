#!/bin/bash

# Multi-Channel Bot Service - Cleanup Script
# Removes all AWS resources created by the project

set -e

REGION="us-east-1"

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

echo "=========================================="
echo -e "${RED}Multi-Channel Bot Service - CLEANUP${NC}"
echo "=========================================="
echo ""
echo -e "${YELLOW}WARNING: This will DELETE all resources!${NC}"
echo ""
read -p "Type 'yes' to confirm: " confirmation

if [ "$confirmation" != "yes" ]; then
    echo "Cleanup cancelled."
    exit 0
fi

echo ""
echo -e "${GREEN}Starting cleanup...${NC}"
echo ""

# 1. Delete Lambda Function URL
echo "[1/7] Deleting Lambda Function URL..."
aws lambda delete-function-url-config --function-name bot-message-router --region $REGION 2>/dev/null || echo "  - Not found"
echo "  ✓ Done"

# 2. Delete Event Source Mapping
echo "[2/7] Deleting SQS Event Source Mapping..."
MAPPINGS=$(aws lambda list-event-source-mappings --function-name bot-nlp-processor --region $REGION 2>/dev/null | jq -r '.EventSourceMappings[].UUID' || echo "")
for uuid in $MAPPINGS; do
    aws lambda delete-event-source-mapping --uuid $uuid --region $REGION
    echo "  ✓ Deleted mapping: $uuid"
done

# 3. Delete Lambda Functions
echo "[3/7] Deleting Lambda Functions..."
for func in bot-message-router bot-nlp-processor; do
    aws lambda delete-function --function-name $func --region $REGION 2>/dev/null && echo "  ✓ Deleted $func" || echo "  - $func not found"
done

# 4. Delete SQS Queues
echo "[4/7] Deleting SQS Queues..."
for queue_name in bot-message-queue bot-message-queue-dlq; do
    QUEUE_URL=$(aws sqs get-queue-url --queue-name $queue_name --region $REGION 2>/dev/null | jq -r '.QueueUrl' || echo "")
    if [ ! -z "$QUEUE_URL" ]; then
        aws sqs delete-queue --queue-url $QUEUE_URL --region $REGION
        echo "  ✓ Deleted $queue_name"
    else
        echo "  - $queue_name not found"
    fi
done

# 5. Delete DynamoDB Tables
echo "[5/7] Deleting DynamoDB Tables..."
for table in Conversations UserSessions IdempotencyKeys RateLimits; do
    aws dynamodb delete-table --table-name $table --region $REGION 2>/dev/null && echo "  ✓ Deleted $table" || echo "  - $table not found"
done

# 6. Delete IAM Role
echo "[6/7] Deleting IAM Role..."
ROLE_NAME="lambda-bot-execution-role"
if aws iam get-role --role-name $ROLE_NAME 2>/dev/null; then
    aws iam delete-role-policy --role-name $ROLE_NAME --policy-name bot-least-privilege 2>/dev/null || true
    aws iam detach-role-policy --role-name $ROLE_NAME --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole 2>/dev/null || true
    aws iam detach-role-policy --role-name $ROLE_NAME --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess 2>/dev/null || true
    aws iam detach-role-policy --role-name $ROLE_NAME --policy-arn arn:aws:iam::aws:policy/AmazonSQSFullAccess 2>/dev/null || true
    aws iam delete-role --role-name $ROLE_NAME
    echo "  ✓ Deleted role"
else
    echo "  - Role not found"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}✓ Cleanup Complete!${NC}"
echo "=========================================="
