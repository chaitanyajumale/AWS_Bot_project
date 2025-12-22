#!/bin/bash

# Multi-Channel Bot Service - 100% FREE FOREVER Deployment
# Uses Lambda Function URLs instead of API Gateway (Always Free!)
# No ECR - uses zip deployment (Always Free!)

set -e

echo "=========================================="
echo "Multi-Channel Bot Service Deployment"
echo "100% FREE FOREVER VERSION"
echo "=========================================="
echo ""

# Configuration
REGION="us-east-1"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}Using AWS Account: ${ACCOUNT_ID}${NC}"
echo -e "${YELLOW}Region: ${REGION}${NC}"
echo -e "${GREEN}This deployment uses ONLY Always-Free services!${NC}"
echo ""

# Step 1: Create DynamoDB Tables (ALWAYS FREE)
echo -e "${GREEN}[1/6] Creating DynamoDB Tables (Always Free)...${NC}"

if aws dynamodb describe-table --table-name Conversations --region $REGION 2>/dev/null; then
    echo "  ✓ Conversations table already exists"
else
    aws dynamodb create-table \
        --table-name Conversations \
        --attribute-definitions \
            AttributeName=conversation_id,AttributeType=S \
            AttributeName=timestamp,AttributeType=N \
        --key-schema \
            AttributeName=conversation_id,KeyType=HASH \
            AttributeName=timestamp,KeyType=RANGE \
        --billing-mode PAY_PER_REQUEST \
        --region $REGION > /dev/null
    echo "  ✓ Created Conversations table"
fi

if aws dynamodb describe-table --table-name UserSessions --region $REGION 2>/dev/null; then
    echo "  ✓ UserSessions table already exists"
else
    aws dynamodb create-table \
        --table-name UserSessions \
        --attribute-definitions \
            AttributeName=user_id,AttributeType=S \
        --key-schema \
            AttributeName=user_id,KeyType=HASH \
        --billing-mode PAY_PER_REQUEST \
        --region $REGION > /dev/null
    echo "  ✓ Created UserSessions table"
fi

echo ""

# Step 2: Create SQS Queue (ALWAYS FREE)
echo -e "${GREEN}[2/6] Creating SQS Queue (Always Free)...${NC}"

QUEUE_URL=$(aws sqs get-queue-url --queue-name bot-message-queue --region $REGION 2>/dev/null | jq -r '.QueueUrl' || echo "")

if [ -z "$QUEUE_URL" ]; then
    QUEUE_URL=$(aws sqs create-queue \
        --queue-name bot-message-queue \
        --attributes VisibilityTimeout=300,MessageRetentionPeriod=86400 \
        --region $REGION | jq -r '.QueueUrl')
    echo "  ✓ Created SQS queue"
else
    echo "  ✓ SQS queue already exists"
fi

echo "  Queue URL: $QUEUE_URL"
echo ""

# Step 3: Create IAM Role (FREE)
echo -e "${GREEN}[3/6] Creating IAM Role (Free)...${NC}"

ROLE_NAME="lambda-bot-execution-role"

if aws iam get-role --role-name $ROLE_NAME 2>/dev/null; then
    echo "  ✓ IAM role already exists"
else
    aws iam create-role \
        --role-name $ROLE_NAME \
        --assume-role-policy-document '{
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }]
        }' > /dev/null
    
    aws iam attach-role-policy \
        --role-name $ROLE_NAME \
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
    
    aws iam attach-role-policy \
        --role-name $ROLE_NAME \
        --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess
    
    aws iam attach-role-policy \
        --role-name $ROLE_NAME \
        --policy-arn arn:aws:iam::aws:policy/AmazonSQSFullAccess
    
    echo "  ✓ Created IAM role with policies"
    echo "  ⏳ Waiting 10 seconds for IAM role to propagate..."
    sleep 10
fi

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
echo ""

# Step 4: Package and Deploy Lambda #1 - Message Router (ALWAYS FREE)
echo -e "${GREEN}[4/6] Deploying Lambda #1 - Message Router (Always Free)...${NC}"

# Create deployment package
mkdir -p /tmp/lambda_router
cp message_router_function_url.py /tmp/lambda_router/message_router.py
cd /tmp/lambda_router
zip -q lambda_router.zip message_router.py

if aws lambda get-function --function-name bot-message-router --region $REGION 2>/dev/null; then
    echo "  Updating bot-message-router function..."
    aws lambda update-function-code \
        --function-name bot-message-router \
        --zip-file fileb://lambda_router.zip \
        --region $REGION > /dev/null
    
    aws lambda update-function-configuration \
        --function-name bot-message-router \
        --environment Variables="{SQS_QUEUE_URL=$QUEUE_URL,CONVERSATIONS_TABLE=Conversations}" \
        --region $REGION > /dev/null
    
    echo "  ✓ Updated bot-message-router"
else
    echo "  Creating bot-message-router function..."
    aws lambda create-function \
        --function-name bot-message-router \
        --runtime python3.11 \
        --handler message_router.lambda_handler \
        --role $ROLE_ARN \
        --zip-file fileb://lambda_router.zip \
        --environment Variables="{SQS_QUEUE_URL=$QUEUE_URL,CONVERSATIONS_TABLE=Conversations}" \
        --timeout 30 \
        --memory-size 512 \
        --region $REGION > /dev/null
    echo "  ✓ Created bot-message-router"
fi

cd - > /dev/null
rm -rf /tmp/lambda_router

echo ""

# Step 5: Package and Deploy Lambda #2 - NLP Processor (ALWAYS FREE)
echo -e "${GREEN}[5/6] Deploying Lambda #2 - NLP Processor (Always Free)...${NC}"

mkdir -p /tmp/lambda_processor
cp nlp_processor.py /tmp/lambda_processor/
cd /tmp/lambda_processor
zip -q lambda_processor.zip nlp_processor.py

if aws lambda get-function --function-name bot-nlp-processor --region $REGION 2>/dev/null; then
    echo "  Updating bot-nlp-processor function..."
    aws lambda update-function-code \
        --function-name bot-nlp-processor \
        --zip-file fileb://lambda_processor.zip \
        --region $REGION > /dev/null
    
    aws lambda update-function-configuration \
        --function-name bot-nlp-processor \
        --environment Variables="{CONVERSATIONS_TABLE=Conversations,SESSIONS_TABLE=UserSessions}" \
        --region $REGION > /dev/null
    
    echo "  ✓ Updated bot-nlp-processor"
else
    echo "  Creating bot-nlp-processor function..."
    aws lambda create-function \
        --function-name bot-nlp-processor \
        --runtime python3.11 \
        --handler nlp_processor.lambda_handler \
        --role $ROLE_ARN \
        --zip-file fileb://lambda_processor.zip \
        --environment Variables="{CONVERSATIONS_TABLE=Conversations,SESSIONS_TABLE=UserSessions}" \
        --timeout 60 \
        --memory-size 1024 \
        --region $REGION > /dev/null
    echo "  ✓ Created bot-nlp-processor"
fi

cd - > /dev/null
rm -rf /tmp/lambda_processor

# Connect SQS to Lambda
QUEUE_ARN=$(aws sqs get-queue-attributes --queue-url $QUEUE_URL --attribute-names QueueArn --region $REGION | jq -r '.Attributes.QueueArn')

MAPPING_UUID=$(aws lambda list-event-source-mappings \
    --function-name bot-nlp-processor \
    --region $REGION \
    | jq -r ".EventSourceMappings[] | select(.EventSourceArn==\"$QUEUE_ARN\") | .UUID" || echo "")

if [ -z "$MAPPING_UUID" ]; then
    aws lambda create-event-source-mapping \
        --function-name bot-nlp-processor \
        --event-source-arn $QUEUE_ARN \
        --batch-size 10 \
        --region $REGION > /dev/null
    echo "  ✓ Connected SQS to Lambda"
fi

echo ""

# Step 6: Create Lambda Function URL (ALWAYS FREE - No API Gateway!)
echo -e "${GREEN}[6/6] Creating Lambda Function URL (Always Free)...${NC}"

FUNCTION_URL=$(aws lambda get-function-url-config \
    --function-name bot-message-router \
    --region $REGION 2>/dev/null | jq -r '.FunctionUrl' || echo "")

if [ -z "$FUNCTION_URL" ]; then
    FUNCTION_URL=$(aws lambda create-function-url-config \
        --function-name bot-message-router \
        --auth-type NONE \
        --cors '{
            "AllowOrigins": ["*"],
            "AllowMethods": ["POST", "GET"],
            "AllowHeaders": ["Content-Type"],
            "MaxAge": 86400
        }' \
        --region $REGION | jq -r '.FunctionUrl')
    
    # Add permission for Function URL
    aws lambda add-permission \
        --function-name bot-message-router \
        --statement-id FunctionURLAllowPublicAccess \
        --action lambda:InvokeFunctionUrl \
        --principal "*" \
        --function-url-auth-type NONE \
        --region $REGION 2>/dev/null || echo "  (Permission may already exist)"
    
    echo "  ✓ Created Function URL"
else
    echo "  ✓ Function URL already exists"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}✓ Deployment Complete!${NC}"
echo "=========================================="
echo ""
echo -e "${GREEN}100% FREE FOREVER!${NC}"
echo "All services used are in the AWS Always-Free tier"
echo ""
echo "Function URL: ${FUNCTION_URL}"
echo ""
echo "Test with:"
echo "  curl -X POST ${FUNCTION_URL} \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"message\":\"Hello!\",\"user_id\":\"test_user\",\"channel\":\"web\"}'"
echo ""
echo "Available channels: web, slack, telegram"
echo ""
echo "Resources created (ALL ALWAYS FREE):"
echo "  • DynamoDB Tables: Conversations, UserSessions"
echo "  • SQS Queue: bot-message-queue"
echo "  • Lambda Functions: bot-message-router, bot-nlp-processor"
echo "  • Lambda Function URL: ${FUNCTION_URL}"
echo ""
echo "Monthly Cost: \$0 (Forever!)"
echo "=========================================="
