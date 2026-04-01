from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

from jose import jwt

from app.config import settings


def hash_password(password: str) -> str:
    """
    PBKDF2-HMAC-SHA256 password hash.
    Format: pbkdf2_sha256$<iterations>$<salt_b64>$<dk_b64>
    """
    iterations = 120_000
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)
    return "pbkdf2_sha256$%d$%s$%s" % (
        iterations,
        base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(dk).decode("ascii").rstrip("="),
    )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        scheme, iter_s, salt_b64, dk_b64 = hashed_password.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iter_s)
        salt = base64.urlsafe_b64decode(_pad_b64(salt_b64))
        expected = base64.urlsafe_b64decode(_pad_b64(dk_b64))
        actual = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, iterations, dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _pad_b64(s: str) -> str:
    return s + "=" * (-len(s) % 4)


def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
