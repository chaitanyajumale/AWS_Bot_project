"""
Lambda Function #1: Message Router (Function URL Version)
Routes incoming messages from multiple channels to SQS queue
Works with Lambda Function URLs (no API Gateway needed - Always Free!)
"""

import json
import logging
import os
from datetime import datetime
import hashlib

import boto3

from bot_common.auth import verify_api_key
from bot_common.idempotency import (
    get_cached_response,
    resolve_idempotency_key,
    store_response,
)
from bot_common.logging_utils import configure_logging, log_event, resolve_correlation_id
from bot_common.rate_limit import check_rate_limit
from bot_common.responses import api_response, error_response
from bot_common.validation import validate_message_request

SERVICE_NAME = "bot-message-router"
logger = configure_logging(SERVICE_NAME)

CONVERSATION_TTL_DAYS = int(os.environ.get("CONVERSATION_TTL_DAYS", "30"))


def _get_sqs():
    g = globals()
    if "sqs" not in g:
        g["sqs"] = boto3.client("sqs")
    return g["sqs"]


def _get_dynamodb():
    g = globals()
    if "dynamodb" not in g:
        g["dynamodb"] = boto3.resource("dynamodb")
    return g["dynamodb"]


def __getattr__(name):
    if name == "sqs":
        return _get_sqs()
    if name == "dynamodb":
        return _get_dynamodb()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def lambda_handler(event, context):
    correlation_id = resolve_correlation_id(event, context)
    aws_request_id = getattr(context, "aws_request_id", None)

    try:
        log_event(
            logger,
            logging.INFO,
            "router.invocation",
            correlation_id=correlation_id,
            service=SERVICE_NAME,
            aws_request_id=aws_request_id,
            method=(event.get("requestContext") or {}).get("http", {}).get("method"),
            path=event.get("rawPath"),
        )

        http_method = (event.get("requestContext") or {}).get("http", {}).get("method", "POST")
        if http_method == "GET":
            return health_check(correlation_id)

        headers = event.get("headers") or {}
        authorized, auth_error = verify_api_key(headers)
        if not authorized:
            return error_response(
                401,
                "UNAUTHORIZED",
                auth_error or "Unauthorized",
                correlation_id=correlation_id,
            )

        body = parse_body(event)
        idempotency_key = resolve_idempotency_key(headers, body)
        if idempotency_key:
            cached = get_cached_response(idempotency_key)
            if cached:
                log_event(
                    logger,
                    logging.INFO,
                    "router.idempotency_hit",
                    correlation_id=correlation_id,
                    service=SERVICE_NAME,
                    idempotency_key=idempotency_key,
                )
                return api_response(200, cached, correlation_id=correlation_id)

        validated, errors = validate_message_request(body)
        if errors:
            return error_response(
                400,
                "VALIDATION_ERROR",
                "Invalid request payload",
                correlation_id=correlation_id,
                details={"fields": errors},
            )

        assert validated is not None
        channel = validated["channel"]
        user_id = validated["user_id"]
        message = validated["message"]

        allowed, rate_error = check_rate_limit(user_id)
        if not allowed:
            return error_response(
                429,
                "RATE_LIMIT_EXCEEDED",
                rate_error or "Too many requests",
                correlation_id=correlation_id,
            )

        conversation_id = generate_conversation_id(user_id, channel)
        store_message(conversation_id, user_id, message, channel, "inbound", correlation_id)

        queue_message = {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "message": message,
            "channel": channel,
            "timestamp": int(datetime.now().timestamp()),
            "correlation_id": correlation_id,
        }

        sqs_response = _get_sqs().send_message(
            QueueUrl=_env("SQS_QUEUE_URL"),
            MessageBody=json.dumps(queue_message),
            MessageAttributes={
                "correlation_id": {"DataType": "String", "StringValue": correlation_id},
            },
        )

        response_body = {
            "status": "queued",
            "message_id": sqs_response["MessageId"],
            "conversation_id": conversation_id,
            "channel": channel,
        }

        if idempotency_key:
            store_response(idempotency_key, response_body)

        log_event(
            logger,
            logging.INFO,
            "router.queued",
            correlation_id=correlation_id,
            service=SERVICE_NAME,
            aws_request_id=aws_request_id,
            conversation_id=conversation_id,
            sqs_message_id=sqs_response["MessageId"],
        )

        return api_response(200, response_body, correlation_id=correlation_id)

    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            "router.error",
            correlation_id=correlation_id,
            service=SERVICE_NAME,
            aws_request_id=aws_request_id,
            error=str(exc),
            exc_info=True,
        )
        return error_response(
            500,
            "INTERNAL_ERROR",
            "Failed to route message",
            correlation_id=correlation_id,
        )


def health_check(correlation_id: str):
    checks = {
        "router": "ok",
        "sqs_configured": bool(_env("SQS_QUEUE_URL")),
        "dynamodb_table": _env("CONVERSATIONS_TABLE", "Conversations"),
    }
    status_code = 200 if checks["sqs_configured"] else 503
    return api_response(
        status_code,
        {
            "status": "healthy" if status_code == 200 else "degraded",
            "service": SERVICE_NAME,
            "checks": checks,
        },
        correlation_id=correlation_id,
    )


def parse_body(event):
    if "body" in event:
        body = event["body"]
        if isinstance(body, str):
            return json.loads(body or "{}")
        return body or {}
    return event


def generate_conversation_id(user_id, channel):
    date_str = datetime.now().strftime("%Y%m%d")
    key = f"{user_id}_{channel}_{date_str}"
    return hashlib.md5(key.encode()).hexdigest()


def store_message(conversation_id, user_id, message, channel, direction, correlation_id):
    table = _get_dynamodb().Table(_env("CONVERSATIONS_TABLE", "Conversations"))
    timestamp = int(datetime.now().timestamp() * 1000)
    ttl = int(datetime.now().timestamp()) + (CONVERSATION_TTL_DAYS * 86400)

    item = {
        "conversation_id": conversation_id,
        "timestamp": timestamp,
        "user_id": user_id,
        "message": message,
        "channel": channel,
        "direction": direction,
        "correlation_id": correlation_id,
        "ttl": ttl,
    }

    table.put_item(Item=item)
    log_event(
        logger,
        logging.INFO,
        "router.stored_inbound",
        correlation_id=correlation_id,
        service=SERVICE_NAME,
        conversation_id=conversation_id,
    )
