"""DynamoDB-backed per-user rate limiting."""

import os
import time
from typing import Optional, Tuple

import boto3
from botocore.exceptions import ClientError

_dynamodb = None


def _get_table():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb")
    return _dynamodb.Table(os.environ.get("RATE_LIMIT_TABLE", "RateLimits"))


def check_rate_limit(user_id: str) -> Tuple[bool, Optional[str]]:
    limit_per_minute = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "60"))
    if limit_per_minute <= 0:
        return True, None

    table = _get_table()
    window_start = int(time.time()) // 60 * 60
    ttl = window_start + 120

    try:
        response = table.update_item(
            Key={"user_id": user_id, "window_start": window_start},
            UpdateExpression="ADD request_count :inc SET #ttl = :ttl",
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={":inc": 1, ":ttl": ttl, ":limit": limit_per_minute},
            ConditionExpression="attribute_not_exists(request_count) OR request_count < :limit",
            ReturnValues="UPDATED_NEW",
        )
        _ = response
        return True, None
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False, f"Rate limit exceeded ({limit_per_minute} requests/minute)"
        return True, None
