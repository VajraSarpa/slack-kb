"""Slack request signature and timestamp check (Slice 1, rung C2)."""

import hashlib
import hmac
import re
from collections.abc import Mapping

MAX_SKEW_SECONDS = 300
TIMESTAMP_HEADER = "x-slack-request-timestamp"
SIGNATURE_HEADER = "x-slack-signature"
_TIMESTAMP_RE = re.compile(r"[0-9]+")


class SignatureError(Exception):
    """The request is not a valid, fresh Slack request. Messages never carry secrets."""


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None


def verify(headers: Mapping[str, str], body: str, secret: str, now: int) -> None:
    """Raise SignatureError unless headers carry a fresh, matching v0 signature for body."""
    timestamp = _header(headers, TIMESTAMP_HEADER)
    signature = _header(headers, SIGNATURE_HEADER)
    if timestamp is None:
        raise SignatureError("missing timestamp header")
    if signature is None:
        raise SignatureError("missing signature header")
    if not _TIMESTAMP_RE.fullmatch(timestamp):
        raise SignatureError("timestamp is not an integer")
    if abs(now - int(timestamp)) > MAX_SKEW_SECONDS:
        raise SignatureError("timestamp outside allowed window")

    base = f"v0:{timestamp}:{body}".encode()
    expected = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected.encode(), signature.encode()):
        raise SignatureError("signature mismatch")
