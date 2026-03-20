# Multi-Channel Bot — deploy Lambdas as container images (ECR + Docker)
# Prerequisites: Docker running, AWS CLI configured
# Note: AWS cannot convert Zip Lambdas to Image in-place. Delete old functions or use -FunctionSuffix.

param(
    [string]$Region = "us-east-1",
    [string]$ImageTag = "latest",
    [string]$FunctionSuffix = ""
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Docker / ECR Lambda deployment" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

$accountInfo = aws sts get-caller-identity | ConvertFrom-Json
$ACCOUNT_ID = $accountInfo.Account
$ROUTER_FN = "bot-message-router$FunctionSuffix"
$NLP_FN = "bot-nlp-processor$FunctionSuffix"
$REGISTRY = "$ACCOUNT_ID.dkr.ecr.$Region.amazonaws.com"
$ROUTER_IMAGE = "$REGISTRY/bot-message-router`:$ImageTag"
$NLP_IMAGE = "$REGISTRY/bot-nlp-processor`:$ImageTag"
$ROLE_NAME = "lambda-bot-execution-role"

Write-Host "Account: $ACCOUNT_ID  Region: $Region" -ForegroundColor Yellow
Write-Host "Functions: $ROUTER_FN , $NLP_FN" -ForegroundColor Yellow
Write-Host ""

# --- [1/8] DynamoDB (same as zip deploy) ---
Write-Host "[1/8] DynamoDB tables..." -ForegroundColor Green
if (-not (aws dynamodb describe-table --table-name Conversations --region $Region 2>$null)) {
    aws dynamodb create-table `
        --table-name Conversations `
        --attribute-definitions AttributeName=conversation_id,AttributeType=S AttributeName=timestamp,AttributeType=N `
        --key-schema AttributeName=conversation_id,KeyType=HASH AttributeName=timestamp,KeyType=RANGE `
        --billing-mode PAY_PER_REQUEST `
        --region $Region | Out-Null
    Write-Host "  Created Conversations" -ForegroundColor Gray
} else { Write-Host "  Conversations exists" -ForegroundColor Gray }

if (-not (aws dynamodb describe-table --table-name UserSessions --region $Region 2>$null)) {
    aws dynamodb create-table `
        --table-name UserSessions `
        --attribute-definitions AttributeName=user_id,AttributeType=S `
        --key-schema AttributeName=user_id,KeyType=HASH `
        --billing-mode PAY_PER_REQUEST `
        --region $Region | Out-Null
    Write-Host "  Created UserSessions" -ForegroundColor Gray
} else { Write-Host "  UserSessions exists" -ForegroundColor Gray }
Write-Host ""

# --- [2/8] SQS ---
Write-Host "[2/8] SQS queue..." -ForegroundColor Green
$queueCheck = aws sqs get-queue-url --queue-name bot-message-queue --region $Region 2>$null
if ($queueCheck) {
    $QUEUE_URL = ($queueCheck | ConvertFrom-Json).QueueUrl
} else {
    $QUEUE_URL = (aws sqs create-queue `
        --queue-name bot-message-queue `
        --attributes VisibilityTimeout=300,MessageRetentionPeriod=86400 `
        --region $Region | ConvertFrom-Json).QueueUrl
    Write-Host "  Created queue" -ForegroundColor Gray
}
Write-Host "  $QUEUE_URL" -ForegroundColor Gray
Write-Host ""

# --- [3/8] IAM role ---
Write-Host "[3/8] IAM role..." -ForegroundColor Green
if (-not (aws iam get-role --role-name $ROLE_NAME 2>$null)) {
    $trustPolicy = @'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}
'@
    $trustPolicy | Out-File -FilePath "trust-policy.json" -Encoding ascii -NoNewline
    aws iam create-role --role-name $ROLE_NAME --assume-role-policy-document file://trust-policy.json | Out-Null
    Remove-Item trust-policy.json -ErrorAction SilentlyContinue
    aws iam attach-role-policy --role-name $ROLE_NAME --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
    aws iam attach-role-policy --role-name $ROLE_NAME --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess
    aws iam attach-role-policy --role-name $ROLE_NAME --policy-arn arn:aws:iam::aws:policy/AmazonSQSFullAccess
    Write-Host "  Created role; waiting 10s for IAM..." -ForegroundColor Gray
    Start-Sleep -Seconds 10
} else { Write-Host "  Role exists" -ForegroundColor Gray }
$ROLE_ARN = "arn:aws:iam:${ACCOUNT_ID}:role/${ROLE_NAME}"
Write-Host ""

# --- [4/8] ECR repos ---
Write-Host "[4/8] ECR repositories..." -ForegroundColor Green
foreach ($repo in @("bot-message-router", "bot-nlp-processor")) {
    aws ecr create-repository --repository-name $repo --region $Region 2>$null | Out-Null
    Write-Host "  $repo" -ForegroundColor Gray
}
Write-Host ""

# --- [5/8] Docker login + build + push ---
Write-Host "[5/8] Docker build & push..." -ForegroundColor Green
$login = aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin $REGISTRY
if ($LASTEXITCODE -ne 0) { throw "docker login failed" }

docker build -f Dockerfile.router -t bot-message-router`:$ImageTag .
if ($LASTEXITCODE -ne 0) { throw "docker build router failed" }
docker tag bot-message-router`:$ImageTag $ROUTER_IMAGE
docker push $ROUTER_IMAGE
if ($LASTEXITCODE -ne 0) { throw "docker push router failed" }

docker build -f Dockerfile.nlp -t bot-nlp-processor`:$ImageTag .
if ($LASTEXITCODE -ne 0) { throw "docker build nlp failed" }
docker tag bot-nlp-processor`:$ImageTag $NLP_IMAGE
docker push $NLP_IMAGE
if ($LASTEXITCODE -ne 0) { throw "docker push nlp failed" }
Write-Host ""

# --- Helper: ensure Lambda is Image or create ---
function Deploy-ImageLambda {
    param(
        [string]$Name,
        [string]$ImageUri,
        [int]$Timeout,
        [int]$Memory,
        [string]$EnvVars
    )
    $exists = aws lambda get-function --function-name $Name --region $Region 2>$null
    if ($exists) {
        $cfg = aws lambda get-function-configuration --function-name $Name --region $Region | ConvertFrom-Json
        if ($cfg.PackageType -ne "Image") {
            throw "Lambda '$Name' is Zip-based. Delete it in the console/CLI or deploy with -FunctionSuffix '-ecr' for new names."
        }
        aws lambda update-function-code --function-name $Name --image-uri $ImageUri --region $Region | Out-Null
        Start-Sleep -Seconds 3
        aws lambda update-function-configuration `
            --function-name $Name `
            --timeout $Timeout `
            --memory-size $Memory `
            --environment $EnvVars `
            --region $Region | Out-Null
        Write-Host "  Updated $Name" -ForegroundColor Gray
    } else {
        aws lambda create-function `
            --function-name $Name `
            --package-type Image `
            --code ImageUri=$ImageUri `
            --role $ROLE_ARN `
            --timeout $Timeout `
            --memory-size $Memory `
            --environment $EnvVars `
            --region $Region | Out-Null
        Write-Host "  Created $Name" -ForegroundColor Gray
    }
}

# --- [6/8] Deploy Lambdas ---
Write-Host "[6/8] Lambda functions (container)..." -ForegroundColor Green
Deploy-ImageLambda -Name $ROUTER_FN -ImageUri $ROUTER_IMAGE -Timeout 30 -Memory 512 `
    -EnvVars "Variables={SQS_QUEUE_URL=$QUEUE_URL,CONVERSATIONS_TABLE=Conversations}"

Deploy-ImageLambda -Name $NLP_FN -ImageUri $NLP_IMAGE -Timeout 60 -Memory 1024 `
    -EnvVars "Variables={CONVERSATIONS_TABLE=Conversations,SESSIONS_TABLE=UserSessions}"
Write-Host ""

# --- [7/8] SQS -> NLP ---
Write-Host "[7/8] SQS event source mapping -> $NLP_FN ..." -ForegroundColor Green
$QUEUE_ARN = (aws sqs get-queue-attributes --queue-url $QUEUE_URL --attribute-names QueueArn --region $Region | ConvertFrom-Json).Attributes.QueueArn
$mappings = aws lambda list-event-source-mappings --function-name $NLP_FN --region $Region | ConvertFrom-Json
$existing = $mappings.EventSourceMappings | Where-Object { $_.EventSourceArn -eq $QUEUE_ARN }
if (-not $existing) {
    aws lambda create-event-source-mapping `
        --function-name $NLP_FN `
        --event-source-arn $QUEUE_ARN `
        --batch-size 10 `
        --region $Region | Out-Null
    Write-Host "  Mapping created" -ForegroundColor Gray
} else { Write-Host "  Mapping exists" -ForegroundColor Gray }
Write-Host ""

# --- [8/8] Function URL on router ---
Write-Host "[8/8] Lambda Function URL ($ROUTER_FN)..." -ForegroundColor Green
$urlCheck = aws lambda get-function-url-config --function-name $ROUTER_FN --region $Region 2>$null
if ($urlCheck) {
    $FUNCTION_URL = ($urlCheck | ConvertFrom-Json).FunctionUrl
    Write-Host "  URL exists" -ForegroundColor Gray
} else {
    $FUNCTION_URL = (aws lambda create-function-url-config `
        --function-name $ROUTER_FN `
        --auth-type NONE `
        --cors "AllowOrigins=*,AllowMethods=POST,AllowMethods=GET,AllowHeaders=Content-Type,MaxAge=86400" `
        --region $Region | ConvertFrom-Json).FunctionUrl
    aws lambda add-permission `
        --function-name $ROUTER_FN `
        --statement-id FunctionURLAllowPublicAccess `
        --action lambda:InvokeFunctionUrl `
        --principal "*" `
        --function-url-auth-type NONE `
        --region $Region 2>$null | Out-Null
    Write-Host "  Created URL" -ForegroundColor Gray
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Done" -ForegroundColor Green
Write-Host $FUNCTION_URL -ForegroundColor White
$FUNCTION_URL | Out-File -FilePath "FUNCTION_URL.txt" -Encoding utf8
Write-Host "Saved FUNCTION_URL.txt" -ForegroundColor Gray
Write-Host "==========================================" -ForegroundColor Cyan
