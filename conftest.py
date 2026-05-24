"""Root conftest.

Sets safe defaults BEFORE any test module (and therefore any production
module under test) is imported. The Lambda modules construct boto3
resources and read configuration at module-import time — correct for
Lambda cold-starts, but it means pytest collection itself triggers
those side effects. CI runners have no AWS config, so we provide a
self-contained environment here.
"""

import os

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "0")
