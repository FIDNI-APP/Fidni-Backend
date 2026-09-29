"""Signed, expiring tokens for email verification.

Uses django.core.signing (HMAC with SECRET_KEY) — no extra dependencies and no
DB table. A token is just a signed, timestamped payload; tampering or expiry is
detected on read.
"""
from django.core import signing

SALT = 'fidni-email-verify'
MAX_AGE_SECONDS = 60 * 60 * 24 * 3  # 3 days


def make_verification_token(user) -> str:
    return signing.dumps({'uid': user.id, 'email': user.email}, salt=SALT)


def read_verification_token(token: str, max_age: int = MAX_AGE_SECONDS) -> dict:
    """Returns the payload dict, or raises signing.SignatureExpired /
    signing.BadSignature."""
    return signing.loads(token, salt=SALT, max_age=max_age)
