"""Standard HTTP responses for Lambda Function URLs."""

import json
from typing import Any, Dict, Optional


def api_response(
    status_code: int,
    body: Dict[str, Any],
    *,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload = dict(body)
    if correlation_id:
        payload["correlation_id"] = correlation_id

    headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type, X-API-Key, X-Correlation-Id, Idempotency-Key",
        "Access-Control-Allow-Methods": "OPTIONS,POST,GET",
    }
    if correlation_id:
        headers["X-Correlation-Id"] = correlation_id

    return {
        "statusCode": status_code,
        "headers": headers,
        "body": json.dumps(payload),
    }


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    correlation_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
        }
    }
    if details:
        body["error"]["details"] = details
    return api_response(status_code, body, correlation_id=correlation_id)
