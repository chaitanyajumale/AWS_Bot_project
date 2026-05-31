"""Authentication for the public Function URL.

Two credential schemes are supported, both optional and independently
configurable via environment variables:

* ``API_KEY``    — a shared secret presented in ``X-API-Key`` or as a
  ``Bearer`` token. Compared in constant time to defeat timing attacks.
* ``JWT_SECRET`` — enables stateless, expiring JWT bearer tokens (HS256),
  verified with the open source PyJWT library.

If neither variable is set the endpoint is open (useful for local dev);
if either is set, a request must satisfy at least one scheme.
"""

import os
from typing import Dict, Optional, Tuple

from bot_common.crypto import secure_compare, verify_token


def _extract_bearer(headers: Dict[str, str]) -> Optional[str]:
    auth_header = (headers.get("authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return None


def verify_api_key(headers: Optional[Dict[str, str]]) -> Tuple[bool, Optional[str]]:
    configured_key = os.environ.get("API_KEY", "").strip()
    jwt_secret = os.environ.get("JWT_SECRET", "").strip()

    # No auth configured -> open endpoint (local/dev convenience).
    if not configured_key and not jwt_secret:
        return True, None

    normalized = {str(k).lower(): v for k, v in (headers or {}).items()}
    bearer = _extract_bearer(normalized)

    # 1) JWT bearer token path.
    if jwt_secret and bearer:
        ok, _claims = verify_token(bearer, jwt_secret)
        if ok:
            return True, None

    # 2) Shared-secret API key path (constant-time comparison).
    if configured_key:
        provided = normalized.get("x-api-key") or bearer
        if provided and secure_compare(provided, configured_key):
            return True, None

    return False, "Invalid or missing credentials"
