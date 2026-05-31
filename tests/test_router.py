import json
import os
from unittest.mock import patch

import boto3
from moto import mock_aws

import message_router_function_url as router


@mock_aws
def test_health_check():
    event = {
        "requestContext": {"http": {"method": "GET"}},
        "rawPath": "/health",
        "headers": {},
    }
    response = router.lambda_handler(event, None)
    assert response["statusCode"] == 503
    body = json.loads(response["body"])
    assert body["status"] == "degraded"


@mock_aws
def test_queue_message_success():
    os.environ["CONVERSATIONS_TABLE"] = "Conversations"
    os.environ["RATE_LIMIT_PER_MINUTE"] = "0"
    os.environ["SQS_QUEUE_URL"] = "https://sqs.us-east-1.amazonaws.com/123456789012/bot-message-queue"

    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(
        TableName="Conversations",
        KeySchema=[
            {"AttributeName": "conversation_id", "KeyType": "HASH"},
            {"AttributeName": "timestamp", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "conversation_id", "AttributeType": "S"},
            {"AttributeName": "timestamp", "AttributeType": "N"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    event = {
        "requestContext": {"http": {"method": "POST"}, "requestId": "req-1"},
        "headers": {"content-type": "application/json"},
        "body": json.dumps({"message": "Hello", "user_id": "user-1", "channel": "web"}),
    }

    with patch.object(
        router.sqs,
        "send_message",
        return_value={"MessageId": "mid-1"},
    ):
        response = router.lambda_handler(event, None)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["status"] == "queued"
    assert "conversation_id" in body
    assert response["headers"]["X-Correlation-Id"]


def test_webhook_signature_rejected_when_invalid():
    body = json.dumps({"message": "Hi", "user_id": "user-1", "channel": "slack"})
    event = {
        "requestContext": {"http": {"method": "POST"}},
        "headers": {"x-signature": "sha256=deadbeef"},
        "body": body,
    }
    with patch.dict(
        os.environ,
        {"SQS_QUEUE_URL": "https://example.com/queue", "WEBHOOK_SIGNING_SECRET": "shhh"},
        clear=False,
    ):
        response = router.lambda_handler(event, None)
    assert response["statusCode"] == 401
    assert json.loads(response["body"])["error"]["code"] == "INVALID_SIGNATURE"


@mock_aws
def test_webhook_signature_accepted_when_valid():
    from bot_common.crypto import compute_signature

    body = json.dumps({"message": "Hi", "user_id": "user-1", "channel": "slack"})
    signature = compute_signature("shhh", body.encode("utf-8"))
    event = {
        "requestContext": {"http": {"method": "POST"}},
        "headers": {"x-signature": signature},
        "body": body,
    }
    with patch.dict(
        os.environ,
        {"SQS_QUEUE_URL": "https://example.com/queue", "WEBHOOK_SIGNING_SECRET": "shhh"},
        clear=False,
    ):
        # Valid signature passes the gate; we don't need SQS to succeed here,
        # only to get past the 401. A missing table surfaces as 500, not 401.
        response = router.lambda_handler(event, None)
    assert response["statusCode"] != 401


def test_validation_error_response():
    event = {
        "requestContext": {"http": {"method": "POST"}},
        "headers": {},
        "body": json.dumps({"channel": "web"}),
    }
    with patch.dict(os.environ, {"SQS_QUEUE_URL": "https://example.com/queue"}, clear=False):
        response = router.lambda_handler(event, None)
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error"]["code"] == "VALIDATION_ERROR"
