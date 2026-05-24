"""Structured JSON logging with correlation ID support for CloudWatch."""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

CORRELATION_HEADER = "x-correlation-id"
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("correlation_id", "service", "aws_request_id", "extra"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(service: str) -> logging.Logger:
    logger = logging.getLogger(service)
    if logger.handlers:
        return logger

    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    logger.propagate = False
    return logger


def resolve_correlation_id(event: dict, context: Any = None) -> str:
    headers = event.get("headers") or {}
    normalized = {str(k).lower(): v for k, v in headers.items()}
    correlation_id = normalized.get(CORRELATION_HEADER) or normalized.get("x-request-id")
    if correlation_id:
        return str(correlation_id)

    request_context = event.get("requestContext") or {}
    correlation_id = request_context.get("requestId")
    if correlation_id:
        return str(correlation_id)

    if context is not None and getattr(context, "aws_request_id", None):
        return str(context.aws_request_id)

    return str(uuid.uuid4())


def log_event(
    logger: logging.Logger,
    level: int,
    message: str,
    *,
    correlation_id: Optional[str] = None,
    service: Optional[str] = None,
    aws_request_id: Optional[str] = None,
    exc_info: bool = False,
    **fields: Any,
) -> None:
    extra = {
        "correlation_id": correlation_id,
        "service": service,
        "aws_request_id": aws_request_id,
        "extra": fields or None,
    }
    logger.log(level, message, extra=extra, exc_info=exc_info)
