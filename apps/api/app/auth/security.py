"""Password hashing (stdlib scrypt) and opaque session tokens.

scrypt parameters n=2**15, r=8, p=1 (~32 MiB memory) follow OWASP guidance for scrypt.
Only the SHA-256 of a session token is stored, so a database leak does not yield usable cookies.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

N, R, P, DKLEN = 2**15, 8, 1, 32
MAXMEM = 64 * 1024 * 1024
MIN_PASSWORD_LENGTH = 12


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, dklen=DKLEN, maxmem=MAXMEM)
    return f"scrypt${N}${R}${P}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, n, r, p, salt, expected = encoded.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=DKLEN, maxmem=MAXMEM
        )
        return hmac.compare_digest(dk, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


# A fixed dummy hash makes failed lookups cost the same as wrong passwords (no user enumeration by timing).
DUMMY_HASH = hash_password("dummy-password-for-timing")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
