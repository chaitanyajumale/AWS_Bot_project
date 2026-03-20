#!/usr/bin/env bash
# Docker / ECR Lambda deployment (Linux/macOS)
set -euo pipefail

REGION="${REGION:-us-east-1}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
FUNCTION_SUFFIX="${FUNCTION_SUFFIX:-}"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
ROUTER_FN="bot-message-router${FUNCTION_SUFFIX}"
NLP_FN="bot-nlp-processor${FUNCTION_SUFFIX}"
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
ROUTER_IMAGE="${REGISTRY}/bot-message-router:${IMAGE_TAG}"
NLP_IMAGE="${REGISTRY}/bot-nlp-processor:${IMAGE_TAG}"
ROLE_NAME="lambda-bot-execution-role"

echo "=========================================="
echo "Docker / ECR Lambda deployment"
echo "Account: ${ACCOUNT_ID}  Region: ${REGION}"
echo "Functions: ${ROUTER_FN} , ${NLP_FN}"
echo "=========================================="

# DynamoDB
echo "[1/8] DynamoDB..."
if ! aws dynamodb describe-table --table-name Conversations --region "$REGION" &>/dev/null; then
  aws dynamodb create-table \
    --table-name Conversations \
    --attribute-definitions AttributeName=conversation_id,AttributeType=S AttributeName=timestamp,AttributeType=N \
    --key-schema AttributeName=conversation_id,KeyType=HASH AttributeName=timestamp,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION" >/dev/null
fi
if ! aws dynamodb describe-table --table-name UserSessions --region "$REGION" &>/dev/null; then
  aws dynamodb create-table \
    --table-name UserSessions \
    --attribute-definitions AttributeName=user_id,AttributeType=S \
    --key-schema AttributeName=user_id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION" >/dev/null
fi

# SQS
echo "[2/8] SQS..."
QUEUE_URL="$(aws sqs get-queue-url --queue-name bot-message-queue --region "$REGION" 2>/dev/null | jq -r '.QueueUrl // empty' || true)"
if [[ -z "$QUEUE_URL" ]]; then
  QUEUE_URL="$(aws sqs create-queue \
    --queue-name bot-message-queue \
    --attributes VisibilityTimeout=300,MessageRetentionPeriod=86400 \
    --region "$REGION" | jq -r '.QueueUrl')"
fi
echo "  $QUEUE_URL"

# IAM
echo "[3/8] IAM..."
if ! aws iam get-role --role-name "$ROLE_NAME" &>/dev/null; then
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
  aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
  aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess
  aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn arn:aws:iam::aws:policy/AmazonSQSFullAccess
  echo "  Waiting 10s for IAM..."
  sleep 10
fi
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

# ECR
echo "[4/8] ECR..."
for repo in bot-message-router bot-nlp-processor; do
  aws ecr create-repository --repository-name "$repo" --region "$REGION" &>/dev/null || true
done

# Docker
echo "[5/8] Docker build & push..."
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
docker build -f Dockerfile.router -t "bot-message-router:${IMAGE_TAG}" .
docker tag "bot-message-router:${IMAGE_TAG}" "$ROUTER_IMAGE"
docker push "$ROUTER_IMAGE"
docker build -f Dockerfile.nlp -t "bot-nlp-processor:${IMAGE_TAG}" .
docker tag "bot-nlp-processor:${IMAGE_TAG}" "$NLP_IMAGE"
docker push "$NLP_IMAGE"

deploy_image_lambda() {
  local NAME="$1" IMAGE_URI="$2" TIMEOUT="$3" MEMORY="$4" ENV_JSON="$5"
  if aws lambda get-function --function-name "$NAME" --region "$REGION" &>/dev/null; then
    PT="$(aws lambda get-function-configuration --function-name "$NAME" --region "$REGION" --query PackageType --output text)"
    if [[ "$PT" != "Image" ]]; then
      echo "ERROR: $NAME is Zip-based. Delete it or set FUNCTION_SUFFIX=-ecr"
      exit 1
    fi
    aws lambda update-function-code --function-name "$NAME" --image-uri "$IMAGE_URI" --region "$REGION" >/dev/null
    sleep 3
    aws lambda update-function-configuration \
      --function-name "$NAME" --timeout "$TIMEOUT" --memory-size "$MEMORY" \
      --environment "$ENV_JSON" --region "$REGION" >/dev/null
    echo "  Updated $NAME"
  else
    aws lambda create-function \
      --function-name "$NAME" \
      --package-type Image \
      --code "ImageUri=${IMAGE_URI}" \
      --role "$ROLE_ARN" \
      --timeout "$TIMEOUT" \
      --memory-size "$MEMORY" \
      --environment "$ENV_JSON" \
      --region "$REGION" >/dev/null
    echo "  Created $NAME"
  fi
}

echo "[6/8] Lambda..."
ROUTER_ENV=$(printf 'Variables={SQS_QUEUE_URL=%s,CONVERSATIONS_TABLE=Conversations}' "$QUEUE_URL")
deploy_image_lambda "$ROUTER_FN" "$ROUTER_IMAGE" 30 512 "$ROUTER_ENV"
deploy_image_lambda "$NLP_FN" "$NLP_IMAGE" 60 1024 'Variables={CONVERSATIONS_TABLE=Conversations,SESSIONS_TABLE=UserSessions}'

echo "[7/8] Event source mapping..."
QUEUE_ARN="$(aws sqs get-queue-attributes --queue-url "$QUEUE_URL" --attribute-names QueueArn --region "$REGION" | jq -r '.Attributes.QueueArn')"
MAPPING="$(aws lambda list-event-source-mappings --function-name "$NLP_FN" --region "$REGION" \
  | jq -r --arg arn "$QUEUE_ARN" '.EventSourceMappings[] | select(.EventSourceArn==$arn) | .UUID' | head -1)"
if [[ -z "$MAPPING" ]]; then
  aws lambda create-event-source-mapping \
    --function-name "$NLP_FN" \
    --event-source-arn "$QUEUE_ARN" \
    --batch-size 10 \
    --region "$REGION" >/dev/null
fi

echo "[8/8] Function URL..."
FUNCTION_URL="$(aws lambda get-function-url-config --function-name "$ROUTER_FN" --region "$REGION" 2>/dev/null | jq -r '.FunctionUrl // empty' || true)"
if [[ -z "$FUNCTION_URL" ]]; then
  FUNCTION_URL="$(aws lambda create-function-url-config \
    --function-name "$ROUTER_FN" \
    --auth-type NONE \
    --cors '{"AllowOrigins":["*"],"AllowMethods":["POST","GET"],"AllowHeaders":["Content-Type"],"MaxAge":86400}' \
    --region "$REGION" | jq -r '.FunctionUrl')"
  aws lambda add-permission \
    --function-name "$ROUTER_FN" \
    --statement-id FunctionURLAllowPublicAccess \
    --action lambda:InvokeFunctionUrl \
    --principal "*" \
    --function-url-auth-type NONE \
    --region "$REGION" &>/dev/null || true
fi

echo "$FUNCTION_URL" > FUNCTION_URL.txt
echo "=========================================="
echo "$FUNCTION_URL"
echo "Saved FUNCTION_URL.txt"
echo "=========================================="
