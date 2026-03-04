# Multi-Channel Bot Service - Windows PowerShell Deployment

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Multi-Channel Bot Service Deployment" -ForegroundColor Cyan
Write-Host "100% FREE FOREVER VERSION" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Configuration
$REGION = "us-east-1"
$ErrorActionPreference = "Continue"

# Get AWS Account ID
Write-Host "Getting AWS account info..." -ForegroundColor Yellow
$accountJson = aws sts get-caller-identity
$accountInfo = $accountJson | ConvertFrom-Json
$ACCOUNT_ID = $accountInfo.Account

Write-Host "Using AWS Account: $ACCOUNT_ID" -ForegroundColor Yellow
Write-Host "Region: $REGION" -ForegroundColor Yellow
Write-Host ""

# Step 1: Create DynamoDB Tables
Write-Host "[1/6] Creating DynamoDB Tables..." -ForegroundColor Green

# Conversations table
$conversationsCheck = aws dynamodb describe-table --table-name Conversations --region $REGION 2>$null
if ($conversationsCheck) {
    Write-Host "  * Conversations table already exists" -ForegroundColor Gray
} else {
    Write-Host "  Creating Conversations table..." -ForegroundColor Gray
    aws dynamodb create-table `
        --table-name Conversations `
        --attribute-definitions AttributeName=conversation_id,AttributeType=S AttributeName=timestamp,AttributeType=N `
        --key-schema AttributeName=conversation_id,KeyType=HASH AttributeName=timestamp,KeyType=RANGE `
        --billing-mode PAY_PER_REQUEST `
        --region $REGION | Out-Null
    Write-Host "  * Created Conversations table" -ForegroundColor Gray
}

# UserSessions table
$sessionsCheck = aws dynamodb describe-table --table-name UserSessions --region $REGION 2>$null
if ($sessionsCheck) {
    Write-Host "  * UserSessions table already exists" -ForegroundColor Gray
} else {
    Write-Host "  Creating UserSessions table..." -ForegroundColor Gray
    aws dynamodb create-table `
        --table-name UserSessions `
        --attribute-definitions AttributeName=user_id,AttributeType=S `
        --key-schema AttributeName=user_id,KeyType=HASH `
        --billing-mode PAY_PER_REQUEST `
        --region $REGION | Out-Null
    Write-Host "  * Created UserSessions table" -ForegroundColor Gray
}

Write-Host ""

# Step 2: Create SQS Queue
Write-Host "[2/6] Creating SQS Queue..." -ForegroundColor Green

$queueCheck = aws sqs get-queue-url --queue-name bot-message-queue --region $REGION 2>$null
if ($queueCheck) {
    $queueData = $queueCheck | ConvertFrom-Json
    $QUEUE_URL = $queueData.QueueUrl
    Write-Host "  * SQS queue already exists" -ForegroundColor Gray
} else {
    Write-Host "  Creating SQS queue..." -ForegroundColor Gray
    $queueResult = aws sqs create-queue `
        --queue-name bot-message-queue `
        --attributes VisibilityTimeout=300,MessageRetentionPeriod=86400 `
        --region $REGION
    $queueData = $queueResult | ConvertFrom-Json
    $QUEUE_URL = $queueData.QueueUrl
    Write-Host "  * Created SQS queue" -ForegroundColor Gray
}

Write-Host "  Queue URL: $QUEUE_URL" -ForegroundColor Gray
Write-Host ""

# Step 3: Create IAM Role
Write-Host "[3/6] Creating IAM Role..." -ForegroundColor Green

$ROLE_NAME = "lambda-bot-execution-role"
$roleCheck = aws iam get-role --role-name $ROLE_NAME 2>$null

if ($roleCheck) {
    Write-Host "  * IAM role already exists" -ForegroundColor Gray
} else {
    Write-Host "  Creating IAM role..." -ForegroundColor Gray
    
    # Create trust policy JSON
    $trustPolicy = @"
{
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "lambda.amazonaws.com"},
        "Action": "sts:AssumeRole"
    }]
}
"@
    
    $trustPolicy | Out-File -FilePath "trust-policy.json" -Encoding utf8
    
    aws iam create-role `
        --role-name $ROLE_NAME `
        --assume-role-policy-document file://trust-policy.json | Out-Null
    
    aws iam attach-role-policy `
        --role-name $ROLE_NAME `
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
    
    aws iam attach-role-policy `
        --role-name $ROLE_NAME `
        --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess
    
    aws iam attach-role-policy `
        --role-name $ROLE_NAME `
        --policy-arn arn:aws:iam::aws:policy/AmazonSQSFullAccess
    
    Remove-Item "trust-policy.json" -ErrorAction SilentlyContinue
    
    Write-Host "  * Created IAM role" -ForegroundColor Gray
    Write-Host "  Waiting 10 seconds for IAM role..." -ForegroundColor Gray
    Start-Sleep -Seconds 10
}

$ROLE_ARN = "arn:aws:iam::$ACCOUNT_ID`:role/$ROLE_NAME"
Write-Host ""

# Step 4: Deploy Lambda 1 - Message Router
Write-Host "[4/6] Deploying Lambda 1 - Message Router..." -ForegroundColor Green

# Create temp directory
$tempDir = Join-Path $env:TEMP "lambda_router_$(Get-Random)"
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

# Copy file
Copy-Item "message_router_function_url.py" "$tempDir\message_router.py"

# Create ZIP
$zipPath = "$tempDir\lambda_router.zip"
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($tempDir, $zipPath)

# Check if function exists
$functionCheck = aws lambda get-function --function-name bot-message-router --region $REGION 2>$null

if ($functionCheck) {
    Write-Host "  Updating bot-message-router..." -ForegroundColor Gray
    
    aws lambda update-function-code `
        --function-name bot-message-router `
        --zip-file "fileb://$zipPath" `
        --region $REGION | Out-Null
    
    Start-Sleep -Seconds 2
    
    aws lambda update-function-configuration `
        --function-name bot-message-router `
        --environment "Variables={SQS_QUEUE_URL=$QUEUE_URL,CONVERSATIONS_TABLE=Conversations}" `
        --region $REGION | Out-Null
    
    Write-Host "  * Updated bot-message-router" -ForegroundColor Gray
} else {
    Write-Host "  Creating bot-message-router..." -ForegroundColor Gray
    
    aws lambda create-function `
        --function-name bot-message-router `
        --runtime python3.11 `
        --handler message_router.lambda_handler `
        --role $ROLE_ARN `
        --zip-file "fileb://$zipPath" `
        --environment "Variables={SQS_QUEUE_URL=$QUEUE_URL,CONVERSATIONS_TABLE=Conversations}" `
        --timeout 30 `
        --memory-size 512 `
        --region $REGION | Out-Null
    
    Write-Host "  * Created bot-message-router" -ForegroundColor Gray
}

# Cleanup
Remove-Item -Recurse -Force $tempDir
Write-Host ""

# Step 5: Deploy Lambda 2 - NLP Processor
Write-Host "[5/6] Deploying Lambda 2 - NLP Processor..." -ForegroundColor Green

# Create temp directory
$tempDir2 = Join-Path $env:TEMP "lambda_processor_$(Get-Random)"
New-Item -ItemType Directory -Path $tempDir2 -Force | Out-Null

# Copy file
Copy-Item "nlp_processor.py" "$tempDir2\nlp_processor.py"

# Create ZIP
$zipPath2 = "$tempDir2\lambda_processor.zip"
[System.IO.Compression.ZipFile]::CreateFromDirectory($tempDir2, $zipPath2)

# Check if function exists
$nlpCheck = aws lambda get-function --function-name bot-nlp-processor --region $REGION 2>$null

if ($nlpCheck) {
    Write-Host "  Updating bot-nlp-processor..." -ForegroundColor Gray
    
    aws lambda update-function-code `
        --function-name bot-nlp-processor `
        --zip-file "fileb://$zipPath2" `
        --region $REGION | Out-Null
    
    Start-Sleep -Seconds 2
    
    aws lambda update-function-configuration `
        --function-name bot-nlp-processor `
        --environment "Variables={CONVERSATIONS_TABLE=Conversations,SESSIONS_TABLE=UserSessions}" `
        --region $REGION | Out-Null
    
    Write-Host "  * Updated bot-nlp-processor" -ForegroundColor Gray
} else {
    Write-Host "  Creating bot-nlp-processor..." -ForegroundColor Gray
    
    aws lambda create-function `
        --function-name bot-nlp-processor `
        --runtime python3.11 `
        --handler nlp_processor.lambda_handler `
        --role $ROLE_ARN `
        --zip-file "fileb://$zipPath2" `
        --environment "Variables={CONVERSATIONS_TABLE=Conversations,SESSIONS_TABLE=UserSessions}" `
        --timeout 60 `
        --memory-size 1024 `
        --region $REGION | Out-Null
    
    Write-Host "  * Created bot-nlp-processor" -ForegroundColor Gray
}

# Cleanup
Remove-Item -Recurse -Force $tempDir2

# Connect SQS to Lambda
Write-Host "  Connecting SQS to Lambda..." -ForegroundColor Gray

$queueAttrs = aws sqs get-queue-attributes `
    --queue-url $QUEUE_URL `
    --attribute-names QueueArn `
    --region $REGION | ConvertFrom-Json

$QUEUE_ARN = $queueAttrs.Attributes.QueueArn

$mappings = aws lambda list-event-source-mappings `
    --function-name bot-nlp-processor `
    --region $REGION | ConvertFrom-Json

$existing = $mappings.EventSourceMappings | Where-Object { $_.EventSourceArn -eq $QUEUE_ARN }

if (-not $existing) {
    aws lambda create-event-source-mapping `
        --function-name bot-nlp-processor `
        --event-source-arn $QUEUE_ARN `
        --batch-size 10 `
        --region $REGION | Out-Null
    Write-Host "  * Connected SQS to Lambda" -ForegroundColor Gray
} else {
    Write-Host "  * SQS already connected" -ForegroundColor Gray
}

Write-Host ""

# Step 6: Create Function URL
Write-Host "[6/6] Creating Lambda Function URL..." -ForegroundColor Green

$urlCheck = aws lambda get-function-url-config `
    --function-name bot-message-router `
    --region $REGION 2>$null

if ($urlCheck) {
    $urlData = $urlCheck | ConvertFrom-Json
    $FUNCTION_URL = $urlData.FunctionUrl
    Write-Host "  * Function URL already exists" -ForegroundColor Gray
} else {
    Write-Host "  Creating Function URL..." -ForegroundColor Gray
    
    $urlResult = aws lambda create-function-url-config `
        --function-name bot-message-router `
        --auth-type NONE `
        --cors "AllowOrigins=*,AllowMethods=POST,AllowMethods=GET,AllowHeaders=Content-Type,MaxAge=86400" `
        --region $REGION
    
    $urlData = $urlResult | ConvertFrom-Json
    $FUNCTION_URL = $urlData.FunctionUrl
    
    aws lambda add-permission `
        --function-name bot-message-router `
        --statement-id FunctionURLAllowPublicAccess `
        --action lambda:InvokeFunctionUrl `
        --principal "*" `
        --function-url-auth-type NONE `
        --region $REGION 2>$null | Out-Null
    
    Write-Host "  * Created Function URL" -ForegroundColor Gray
}

# Final output
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "DEPLOYMENT COMPLETE!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "100% FREE FOREVER!" -ForegroundColor Green
Write-Host ""
Write-Host "Function URL:" -ForegroundColor Yellow
Write-Host $FUNCTION_URL -ForegroundColor White
Write-Host ""
Write-Host "Test with PowerShell:" -ForegroundColor Gray
Write-Host '$body = @{message="Hello!";user_id="test";channel="web"} | ConvertTo-Json' -ForegroundColor White
Write-Host "Invoke-RestMethod -Method Post -Uri '$FUNCTION_URL' -Headers @{'Content-Type'='application/json'} -Body `$body" -ForegroundColor White
Write-Host ""
Write-Host "Test with curl:" -ForegroundColor Gray
Write-Host "curl -X POST $FUNCTION_URL -H 'Content-Type: application/json' -d '{`"message`":`"Hello!`",`"user_id`":`"test`",`"channel`":`"web`"}'" -ForegroundColor White
Write-Host ""
Write-Host "Monthly Cost: `$0 (Forever!)" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan

# Save URL to file
$FUNCTION_URL | Out-File -FilePath "FUNCTION_URL.txt" -Encoding utf8
Write-Host ""
Write-Host "Function URL saved to: FUNCTION_URL.txt" -ForegroundColor Green
Write-Host ""