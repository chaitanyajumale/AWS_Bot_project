# Docker & ECR deployment for this project

Your zip-based Lambdas (`deploy_windows.ps1` / `deploy_free_forever.sh`) are unchanged. Use this when you want **container images** on Lambda (heavier dependencies, exact OS/libs, or aligning with a container-first pipeline).

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine) running  
- AWS CLI configured (`aws configure`)  
- IAM permission for **ECR** (push/pull) and **Lambda** (create/update functions)

## Images in this repo

| File              | Lambda role        | ECR repo name (default)   |
|-------------------|--------------------|---------------------------|
| `Dockerfile.router` | `bot-message-router`   | `bot-message-router`      |
| `Dockerfile.nlp`    | `bot-nlp-processor`    | `bot-nlp-processor`       |

Both use **`public.ecr.aws/lambda/python:3.11`**, which already includes **boto3** — no `pip install` needed for the current code.

## Important: Zip → Image on Lambda

AWS **does not** let you switch an existing function from **Zip** to **Image**. You must either:

1. **Delete** the existing Lambda (`bot-message-router` / `bot-nlp-processor`) and run the Docker deploy script, or  
2. Deploy **new** function names (e.g. `bot-message-router-ecr`) and point the Function URL / SQS trigger at those.

The PowerShell script **`deploy_docker.ps1`** checks package type and stops with a clear error if there is a conflict.

## One-command deploy

**Windows** (project root — same folder as the Dockerfiles):

```powershell
.\deploy_docker.ps1
```

Optional:

```powershell
# New function names so zip-based Lambdas can stay in the account
.\deploy_docker.ps1 -FunctionSuffix "-ecr"

.\deploy_docker.ps1 -Region "us-west-2" -ImageTag "v1"
```

**Linux / macOS:**

```bash
chmod +x deploy_docker.sh
./deploy_docker.sh
# or: REGION=us-west-2 IMAGE_TAG=v1 FUNCTION_SUFFIX=-ecr ./deploy_docker.sh
```

## Manual steps (any OS)

Set variables:

```bash
REGION=us-east-1
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
```

### 1. ECR repositories

```bash
aws ecr create-repository --repository-name bot-message-router --region $REGION 2>/dev/null || true
aws ecr create-repository --repository-name bot-nlp-processor --region $REGION 2>/dev/null || true
```

### 2. Log in to ECR

```bash
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $REGISTRY
```

### 3. Build, tag, push — router

```bash
docker build -f Dockerfile.router -t bot-message-router:latest .
docker tag bot-message-router:latest $REGISTRY/bot-message-router:latest
docker push $REGISTRY/bot-message-router:latest
```

### 4. Build, tag, push — NLP

```bash
docker build -f Dockerfile.nlp -t bot-nlp-processor:latest .
docker tag bot-nlp-processor:latest $REGISTRY/bot-nlp-processor:latest
docker push $REGISTRY/bot-nlp-processor:latest
```

### 5. Create or update Lambda (Image package type)

**Router** (replace `ROLE_ARN` and `QUEUE_URL` with your values from the zip deploy or AWS console):

```bash
IMAGE_URI=$REGISTRY/bot-message-router:latest

# Create (first time only, Image package)
aws lambda create-function \
  --function-name bot-message-router \
  --package-type Image \
  --code ImageUri=$IMAGE_URI \
  --role ROLE_ARN \
  --timeout 30 \
  --memory-size 512 \
  --environment Variables="{SQS_QUEUE_URL=QUEUE_URL,CONVERSATIONS_TABLE=Conversations}" \
  --region $REGION

# Later code changes: rebuild/push image, then:
aws lambda update-function-code \
  --function-name bot-message-router \
  --image-uri $IMAGE_URI \
  --region $REGION
```

**NLP processor:**

```bash
IMAGE_URI=$REGISTRY/bot-nlp-processor:latest

aws lambda create-function \
  --function-name bot-nlp-processor \
  --package-type Image \
  --code ImageUri=$IMAGE_URI \
  --role ROLE_ARN \
  --timeout 60 \
  --memory-size 1024 \
  --environment Variables="{CONVERSATIONS_TABLE=Conversations,SESSIONS_TABLE=UserSessions}" \
  --region $REGION
```

### 6. SQS event source mapping & Function URL

Same as zip deploy: attach **SQS** → `bot-nlp-processor` (`batch-size 10`), create **Function URL** on **only** `bot-message-router`. Easiest path: run **`deploy_windows.ps1` once** to create DynamoDB/SQS/IAM/mappings, then **replace** both Lambdas with container versions using the commands above — or run **`deploy_docker.ps1`** after infra exists.

## Adding Python dependencies later

Edit the Dockerfile, for example:

```dockerfile
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r requirements.txt
```

Keep the base image as `public.ecr.aws/lambda/python:3.11` so the Lambda runtime contract stays valid.

## Cold starts

Container images are often **larger** than zip-only functions; expect **equal or higher** cold start vs your current minimal zip. Tune **memory** (also increases CPU) and avoid importing heavy libs at module top level when possible.
