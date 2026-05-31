# Security Policy

## Overview

This service runs on AWS Lambda behind HTTPS-only Function URLs. All
cryptographic operations live in a single audited module,
[`bot_common/crypto.py`](bot_common/crypto.py), and are built on maintained
open source libraries (`cryptography`, `PyJWT`) rather than hand-rolled code.

## Authentication & integrity

| Control | Implementation | Configured by |
| --- | --- | --- |
| Shared-secret API key | Constant-time `hmac.compare_digest` | `API_KEY` |
| JWT bearer tokens | HS256 via PyJWT; enforces `exp`, `iat`, `iss`; rejects `alg:none` | `JWT_SECRET` |
| Webhook signatures | HMAC-SHA256 over the raw body (`cryptography`), constant-time verify | `WEBHOOK_SIGNING_SECRET` |
| Conversation IDs | SHA-256 (not MD5) | — |
| Rate limiting | Per-user, per-minute counter in DynamoDB | `RATE_LIMIT_PER_MINUTE` |

Each auth control is optional and independently enabled via its environment
variable, so local development is frictionless while production is locked down.
Secrets are expected to be injected from the environment (e.g. AWS SSM
Parameter Store / Secrets Manager) and are never committed to the repo.

## Secret management

- Use a JWT/signing secret of **at least 32 bytes** (RFC 7518 §3.2).
- Rotate `API_KEY`, `JWT_SECRET`, and `WEBHOOK_SIGNING_SECRET` periodically.
- The IAM policy in `infrastructure/iam-lambda-policy.json` follows least
  privilege.

## Automated security testing

Every push runs, and the build fails on any finding:

- **Bandit** — static analysis (SAST) of the Python source.
- **pip-audit** — known-vulnerability (CVE) scan of runtime dependencies.
- **pytest** — security unit tests in `tests/test_crypto.py` and
  `tests/test_auth.py` (constant-time comparison, signature tampering, JWT
  expiry, wrong-secret, and `alg:none` forgery).

## Reporting a vulnerability

This is an educational/portfolio project. Please open a GitHub issue (omit any
sensitive details) to report a security concern.
