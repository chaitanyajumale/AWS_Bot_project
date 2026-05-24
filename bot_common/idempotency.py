"""Idempotency key storage to prevent duplicate side effects."""

import json
import os
import time
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError

_dynamodb = boto3.resource("dynamodb")
_table_name = os.environ.get("IDEMPOTENCY_TABLE", "IdempotencyKeys")
_ttl_seconds = int(os.environ.get("IDEMPOTENCY_TTL_SECONDS", "86400"))


def resolve_idempotency_key(headers: Optional[Dict[str, str]], body: Dict[str, Any]) -> Optional[str]:
    normalized = {str(k).lower(): v for k, v in (headers or {}).items()}
    key = normalized.get("idempotency-key") or body.get("idempotency_key")
    if not key:
        return None
    key = str(key).strip()
    return key[:128] if key else None


def get_cached_response(idempotency_key: str) -> Optional[Dict[str, Any]]:
    table = _dynamodb.Table(_table_name)
    try:
        item = table.get_item(Key={"idempotency_key": idempotency_key}).get("Item")
        if not item:
            return None
        return json.loads(item["response_body"])
    except Exception:
        return None


def store_response(idempotency_key: str, response_body: Dict[str, Any]) -> None:
    table = _dynamodb.Table(_table_name)
    expires_at = int(time.time()) + _ttl_seconds
    table.put_item(
        Item={
            "idempotency_key": idempotency_key,
            "response_body": json.dumps(response_body),
            "created_at": int(time.time()),
            "expires_at": expires_at,
            "ttl": expires_at,
        }
    )


def claim_processing_key(processing_key: str) -> bool:
    """Return True if this worker should process the message."""
    table = _dynamodb.Table(_table_name)
    expires_at = int(time.time()) + _ttl_seconds
    try:
        table.put_item(
            Item={
                "idempotency_key": processing_key,
                "status": "processing",
                "created_at": int(time.time()),
                "expires_at": expires_at,
                "ttl": expires_at,
            },
            ConditionExpression="attribute_not_exists(idempotency_key)",
        )
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        return True
