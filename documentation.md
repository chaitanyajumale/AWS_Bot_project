# Multi-Channel Bot Service — Documentation

## Table of Contents

1. [Project Overview](#project-overview)
2. [System Architecture](#system-architecture)
3. [Tech Stack](#tech-stack)
4. [AWS Services Used](#aws-services-used)
5. [Project Structure](#project-structure)
6. [Component Details](#component-details)
7. [Data Flow](#data-flow)
8. [Deployment Guide](#deployment-guide)
9. [Testing](#testing)
10. [NLP Intent System](#nlp-intent-system)
11. [DynamoDB Schema](#dynamodb-schema)
12. [Configuration](#configuration)
13. [Cost Optimization](#cost-optimization)
14. [Troubleshooting](#troubleshooting)

---

## Project Overview

The Multi-Channel Bot Service is a production-grade, serverless chatbot platform built on AWS cloud infrastructure. It leverages an event-driven architecture to process natural language messages asynchronously, supporting multiple communication channels (Web, Slack, Telegram, Discord) through RESTful API endpoints.

The platform is designed to operate entirely within AWS Free Tier limits, processing 50K+ messages monthly at zero infrastructure cost while maintaining sub-500ms response latency and 99.9% uptime.

**Key Capabilities:**

- Automatic scaling from 0 to 1000+ concurrent users
- Regex-based NLP for intent recognition and entity extraction
- Persistent conversation context with DynamoDB
- Asynchronous message processing via SQS queuing
- Multi-channel support via RESTful API endpoints
- Zero-cost operation within AWS Free Tier

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Client (Web/Slack/Discord/Telegram)       │
│                         HTTP POST Request                    │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│           Lambda Function #1: Message Router                │
│           (bot-message-router)                              │
│                                                             │
│   1. Extract message from channel-specific format           │
│   2. Generate unique conversation ID                        │
│   3. Store incoming message in DynamoDB                     │
│   4. Queue message to SQS for async processing              │
│                                                             │
│   Runtime: Python 3.11 | Memory: 512 MB | Timeout: 30s     │
└──────────────────────────┬──────────────────────────────────┘
                           │ Send Message
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                SQS Queue: bot-message-queue                 │
│                                                             │
│   - Decouples message ingestion from processing             │
│   - Handles traffic spikes (buffering)                      │
│   - Enables async processing                                │
│   - Automatic retry on failures                             │
│                                                             │
│   Visibility Timeout: 300s | Retention: 1 day               │
│   Batch Size: 10 messages                                   │
└──────────────────────────┬──────────────────────────────────┘
                           │ Event Source Mapping (Poll)
                           ▼
┌─────────────────────────────────────────────────────────────┐
│         Lambda Function #2: NLP Processor                   │
│         (bot-nlp-processor)                                 │
│                                                             │
│   1. Extract intent using regex patterns                    │
│   2. Calculate confidence score                             │
│   3. Generate contextual response                           │
│   4. Update user session data                               │
│   5. Store bot response in DynamoDB                         │
│   6. Log analytics                                          │
│                                                             │
│   Runtime: Python 3.11 | Memory: 1024 MB | Timeout: 60s    │
└──────────────────────────┬──────────────────────────────────┘
                           │ Write
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              DynamoDB Tables                                │
│                                                             │
│   TABLE 1: Conversations                                    │
│   - Primary Key: conversation_id (HASH)                     │
│   - Sort Key: timestamp (RANGE)                             │
│                                                             │
│   TABLE 2: UserSessions                                     │
│   - Primary Key: user_id (HASH)                             │
│   - Stores: User activity and intent history                │
│                                                             │
│   Billing: Pay-per-request (Free tier: 25GB + 25 R/W units)│
└─────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Category          | Technology                          |
|-------------------|-------------------------------------|
| Language          | Python 3.11                         |
| AWS SDK           | boto3                               |
| Compute           | AWS Lambda (serverless functions)   |
| Message Queue     | Amazon SQS                          |
| Database          | Amazon DynamoDB (NoSQL)             |
| API Endpoint      | Lambda Function URL (with CORS)     |
| IAM               | AWS IAM (role-based access)         |
| Monitoring        | Amazon CloudWatch                   |
| Deployment        | PowerShell / Bash scripts           |

---

## AWS Services Used

### AWS Lambda
Two Lambda functions handle the chatbot logic:
- **bot-message-router** (512 MB, 30s timeout): Receives HTTP requests, validates input, stores messages in DynamoDB, and queues them to SQS.
- **bot-nlp-processor** (1024 MB, 60s timeout): Polls SQS, performs NLP intent recognition, generates responses, and updates conversation state in DynamoDB.

### Amazon SQS
- **Queue Name**: `bot-message-queue`
- Decouples ingestion from processing for reliability and scalability.
- Batch processing of up to 10 messages at a time.
- Automatic retry on Lambda processing failures.

### Amazon DynamoDB
- Two tables: `Conversations` and `UserSessions`.
- Pay-per-request billing mode (no provisioned capacity management).
- Supports persistent conversation history and user session tracking.

### IAM Role
- **Role Name**: `lambda-bot-execution-role`
- Attached Policies: `AWSLambdaBasicExecutionRole`, `AmazonDynamoDBFullAccess`, `AmazonSQSFullAccess`

---

## Project Structure

```
Boto_project/
├── message_router_function_url.py   # Lambda 1 — Message Router
├── nlp_processor.py                 # Lambda 2 — NLP Intent Processor
├── deploy_windows.ps1               # PowerShell deployment script (Windows)
├── deploy.sh                        # Bash deployment script (Linux/Mac)
├── FUNCTION_URL.txt                 # Generated API endpoint after deployment
├── .gitignore                       # Git ignore rules
└── README.md                        # Project README
```

---

## Component Details

### Lambda 1: Message Router (`message_router_function_url.py`)

This function serves as the entry point for all incoming messages. It is exposed via a Lambda Function URL with CORS enabled.

**Responsibilities:**
- Receives HTTP POST requests from any channel
- Validates and extracts message payload (`message`, `user_id`, `channel`)
- Generates a unique `conversation_id` using UUID
- Stores the inbound message in the `Conversations` DynamoDB table
- Sends the message to SQS for asynchronous NLP processing
- Returns a confirmation response with the queued `message_id`

**Environment Variables:**
- `SQS_QUEUE_URL`: URL of the SQS queue
- `CONVERSATIONS_TABLE`: Name of the Conversations DynamoDB table

### Lambda 2: NLP Processor (`nlp_processor.py`)

This function is triggered automatically via an SQS Event Source Mapping whenever messages arrive in the queue.

**Responsibilities:**
- Polls and processes batches of up to 10 messages from SQS
- Performs intent recognition using compiled regex patterns
- Calculates a confidence score for detected intents
- Generates contextual responses from predefined templates
- Updates the `UserSessions` table with the latest intent and activity
- Stores the bot's outbound response in the `Conversations` table

**Environment Variables:**
- `CONVERSATIONS_TABLE`: Name of the Conversations DynamoDB table
- `SESSIONS_TABLE`: Name of the UserSessions DynamoDB table

---

## Data Flow

Here is a step-by-step walkthrough of a single message lifecycle:

```
User sends: "Hello, I need help!"

1. HTTP POST → Lambda Function URL
   Body: {"message": "Hello, I need help!", "user_id": "user123", "channel": "web"}

2. Lambda 1 (Message Router)
   → Extracts: message="Hello, I need help!", user_id="user123"
   → Generates: conversation_id="abc123def456..."
   → Stores in DynamoDB: {conversation_id, timestamp, message, direction="inbound"}
   → Queues to SQS: JSON payload with all metadata
   → Returns: {status: "queued", message_id: "sqs-msg-id"}

3. SQS Queue (bot-message-queue)
   → Holds message until Lambda 2 polls
   → Delivers in batches of up to 10

4. Lambda 2 (NLP Processor)
   → Receives message batch from SQS
   → Detects intent: "help" (matches pattern: \b(help|assist)\b)
   → Confidence: 0.7
   → Generates response: "I'm here to help! You can ask me about..."
   → Updates UserSessions: {user_id, last_intent="help", session_count++}
   → Stores response in DynamoDB: {conversation_id, timestamp, response, direction="outbound"}
```

---

## Deployment Guide

### Prerequisites

1. **AWS CLI** installed and configured:
   ```bash
   aws configure
   # Access Key ID: <your-key>
   # Secret Access Key: <your-secret>
   # Region: us-east-1
   # Output format: json
   ```

2. **Python 3.11** installed on your system.

3. An **AWS account** with Free Tier access.

### Deployment (Windows — PowerShell)

```powershell
cd E:\_NEU_Uni_stuff\Boto_project
.\deploy_windows.ps1
```

### Deployment (Linux/Mac — Bash)

```bash
cd /path/to/Boto_project
chmod +x deploy.sh
./deploy.sh
```

### What the Deployment Script Does

The deployment script is idempotent (safe to run multiple times) and performs these steps in order:

| Step | Action                                      | Details                                              |
|------|---------------------------------------------|------------------------------------------------------|
| 1    | Create DynamoDB Tables                      | `Conversations` (HASH+RANGE) and `UserSessions` (HASH) |
| 2    | Create SQS Queue                            | `bot-message-queue` with 300s visibility timeout      |
| 3    | Create IAM Role                             | `lambda-bot-execution-role` with Lambda, DynamoDB, SQS policies |
| 4    | Deploy Lambda 1 (Message Router)            | Packages and deploys `message_router_function_url.py` |
| 5    | Deploy Lambda 2 (NLP Processor)             | Packages and deploys `nlp_processor.py` with SQS trigger |
| 6    | Create Function URL                         | Public HTTPS endpoint with CORS; saves to `FUNCTION_URL.txt` |

### Post-Deployment

After successful deployment, your API endpoint is saved in `FUNCTION_URL.txt` and printed to the console. Use this URL for all API interactions.

---

## Testing

### Using curl

```bash
curl -X POST https://YOUR_FUNCTION_URL \
  -H "Content-Type: application/json" \
  -d '{"message":"Hello!","user_id":"test","channel":"web"}'
```

### Using PowerShell

```powershell
$body = @{message="Hello!"; user_id="test"; channel="web"} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri 'YOUR_FUNCTION_URL' -Headers @{'Content-Type'='application/json'} -Body $body
```

### Expected Response

```json
{
  "status": "queued",
  "message_id": "sqs-message-id-here",
  "conversation_id": "generated-uuid"
}
```

---

## NLP Intent System

The NLP Processor uses regex-based pattern matching to classify user messages into predefined intents. Each intent has associated response templates that are selected randomly for variety.

### Supported Intents

| Intent     | Pattern                                                        | Example Input              |
|------------|----------------------------------------------------------------|----------------------------|
| `greeting` | `\b(hi\|hello\|hey\|greetings\|good (morning\|afternoon\|evening))\b` | "Hello there!"            |
| `farewell` | `\b(bye\|goodbye\|see you\|later\|farewell)\b`                | "Goodbye, thanks!"        |
| `help`     | `\b(help\|support\|assist\|assistance\|guide\|how to)\b`       | "I need help"             |
| `status`   | `\b(status\|how\|what\|info\|information\|update)\b`           | "What's the status?"      |
| `thanks`   | `\b(thanks\|thank you\|thx\|appreciate\|grateful)\b`          | "Thank you so much"       |
| `question` | `\b(what\|when\|where\|who\|why\|how\|which\|can you)\b`      | "What can you do?"        |
| `problem`  | `\b(issue\|problem\|error\|bug\|not working\|broken\|fail)\b` | "It's not working"        |
| `feedback` | `\b(feedback\|comment\|suggestion\|opinion\|think)\b`         | "I have a suggestion"     |
| `default`  | *(no match)*                                                   | "asdfghjkl"               |

### Confidence Scoring

Each detected intent returns a confidence score (0.0–1.0) based on the number and quality of pattern matches in the input message.

---

## DynamoDB Schema

### Conversations Table

| Attribute        | Type   | Key Type  | Description                           |
|------------------|--------|-----------|---------------------------------------|
| `conversation_id`| String | HASH (PK) | Unique conversation identifier (UUID) |
| `timestamp`      | Number | RANGE (SK)| Unix timestamp of the message         |
| `user_id`        | String | —         | Identifier of the user                |
| `message`        | String | —         | Message content                       |
| `channel`        | String | —         | Source channel (web, slack, etc.)      |
| `direction`      | String | —         | `inbound` or `outbound`               |
| `intent`         | String | —         | Detected intent (outbound only)       |
| `confidence`     | Number | —         | Intent confidence score               |

### UserSessions Table

| Attribute        | Type   | Key Type  | Description                           |
|------------------|--------|-----------|---------------------------------------|
| `user_id`        | String | HASH (PK) | Unique user identifier                |
| `last_intent`    | String | —         | Most recently detected intent         |
| `last_activity`  | String | —         | Timestamp of last interaction         |
| `session_count`  | Number | —         | Total number of sessions              |
| `channel`        | String | —         | Last used channel                     |
| `intent_history` | List   | —         | Array of past intents                 |

---

## Configuration

### Lambda Function URL — CORS Settings

```
AllowOrigins:  *
AllowMethods:  POST, GET
AllowHeaders:  Content-Type
MaxAge:        86400 (24 hours)
AuthType:      NONE (public access)
```

### IAM Trust Policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "lambda.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

### Attached IAM Policies

- `AWSLambdaBasicExecutionRole` — CloudWatch logging
- `AmazonDynamoDBFullAccess` — Read/write DynamoDB tables
- `AmazonSQSFullAccess` — Send/receive SQS messages

---

## Cost Optimization

This project is designed to operate entirely within the **AWS Free Tier**:

| Service    | Free Tier Limit                      | Project Usage       |
|------------|--------------------------------------|---------------------|
| Lambda     | 1M requests + 400K GB-seconds/month  | Well under limit    |
| DynamoDB   | 25 GB storage + 25 R/W capacity units | Minimal storage     |
| SQS        | 1M requests/month                    | Well under limit    |
| CloudWatch | 10 custom metrics + 5 GB logs        | Basic logging only  |

**Monthly cost: $0.00** (within free tier limits)

### Strategies Used

- Pay-per-request billing on DynamoDB (no idle provisioned capacity)
- Lambda memory tuned to minimum required (512 MB / 1024 MB)
- SQS batch processing (10 messages per invocation) to reduce Lambda invocations
- No NAT Gateway, no API Gateway (uses Lambda Function URLs instead)

---

## Troubleshooting

### Common Issues

**Deployment script fails with IAM errors:**
IAM role propagation can take up to 10 seconds. The deployment script includes a wait, but if you see permission errors, wait 30 seconds and re-run.

**Lambda function times out:**
Check CloudWatch logs for the specific function. The Message Router has a 30s timeout and the NLP Processor has 60s. If processing is consistently slow, consider increasing memory allocation.

**SQS messages not being processed:**
Verify the Event Source Mapping exists between `bot-message-queue` and `bot-nlp-processor`:
```bash
aws lambda list-event-source-mappings --function-name bot-nlp-processor
```

**DynamoDB table already exists:**
The deployment script is idempotent — it checks if resources exist before creating them. This error is safely skipped.

**Function URL returns 403:**
Ensure the public access permission is set:
```bash
aws lambda get-policy --function-name bot-message-router
```

### Viewing Logs

```bash
# Message Router logs
aws logs tail /aws/lambda/bot-message-router --follow

# NLP Processor logs
aws logs tail /aws/lambda/bot-nlp-processor --follow
```

---

## Author

**Chaitanya** — Northeastern University, MS in Computer Science (2025–2027)

---

## License

MIT License