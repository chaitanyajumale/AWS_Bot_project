"""Optional API key authentication for the public Function URL."""

import os
from typing import Dict, Optional, Tuple


def verify_api_key(headers: Optional[Dict[str, str]]) -> Tuple[bool, Optional[str]]:
    configured_key = os.environ.get("API_KEY", "").strip()
    if not configured_key:
        return True, None

    normalized = {str(k).lower(): v for k, v in (headers or {}).items()}
    provided = normalized.get("x-api-key") or normalized.get("authorization", "").removeprefix("Bearer ").strip()
    if not provided or provided != configured_key:
        return False, "Invalid or missing API key"
    return True, None
