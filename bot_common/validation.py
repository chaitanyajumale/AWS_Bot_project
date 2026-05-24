"""Request validation for inbound webhook payloads."""

import re
from typing import Any, Dict, List, Optional, Tuple

MAX_MESSAGE_LENGTH = 4000
MAX_USER_ID_LENGTH = 128
SUPPORTED_CHANNELS = {"web", "slack", "telegram", "discord"}


def _clean_text(value: Any, max_length: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text[:max_length]


def validate_message_request(body: Dict[str, Any]) -> Tuple[Optional[Dict[str, str]], List[str]]:
    errors: List[str] = []

    channel = _clean_text(body.get("channel"), 32) or "web"
    if channel not in SUPPORTED_CHANNELS:
        errors.append(f"channel must be one of: {', '.join(sorted(SUPPORTED_CHANNELS))}")

    user_id = _clean_text(body.get("user_id") or body.get("userId"), MAX_USER_ID_LENGTH)
    if not user_id:
        if channel == "slack":
            user_id = _clean_text((body.get("event") or {}).get("user"), MAX_USER_ID_LENGTH)
        elif channel == "telegram":
            from_obj = ((body.get("message") or {}).get("from") or {})
            user_id = _clean_text(from_obj.get("id"), MAX_USER_ID_LENGTH)
    if not user_id:
        errors.append("user_id is required")

    message = _clean_text(body.get("message"), MAX_MESSAGE_LENGTH)
    if not message and channel == "slack":
        message = _clean_text((body.get("event") or {}).get("text"), MAX_MESSAGE_LENGTH)
    if not message and channel == "telegram":
        message = _clean_text((body.get("message") or {}).get("text"), MAX_MESSAGE_LENGTH)
    if not message:
        errors.append("message is required and must be non-empty")

    if errors:
        return None, errors

    assert user_id is not None
    assert message is not None
    return {"channel": channel, "user_id": user_id, "message": message}, []
