"""Authentication for the PhysioLive VM.

Two entry points, one output shape.

Passphrase route
    Client POSTs { "passphrase": "...", "display_name": "..." } to
    /auth/login. The passphrase is compared to a bcrypt hash stored in
    the `PHYSIOLIVE_PASSPHRASE_HASH` env var; if it matches the client
    receives a signed JWT.

Google route
    Client POSTs { "id_token": "..." } to /auth/google. The token is
    verified against Google's tokeninfo endpoint (a network call, but
    it also validates the signature and audience). If the resulting
    email is on the whitelist in `PHYSIOLIVE_ALLOWED_EMAILS` the client
    receives the same shape of JWT.

Both flows return
    {
        "jwt": "eyJhbGciOiJI...",
        "exp": 1700000000,           # unix seconds
        "profile": {                  # what the UI displays
            "sub": "u_<hex>",
            "email": "...",
            "name": "...",
            "picture": "...",
            "source": "google" | "passphrase"
        }
    }

The JWT is HS256 signed with `PHYSIOLIVE_JWT_SECRET` (auto-generated
and persisted at first boot when unset). The claim set is:
    { sub, email, name, source, iat, exp }

`require_auth()` verifies incoming Bearer tokens on protected routes.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import time
from pathlib import Path
from typing import Dict, Optional, Set

import bcrypt
import httpx
import jwt as pyjwt
from fastapi import Header, HTTPException


# ------------------------------------------------------------------ config

_JWT_ALG = "HS256"
_JWT_TTL_SECONDS = int(os.environ.get("PHYSIOLIVE_JWT_TTL", str(7 * 24 * 3600)))
_SECRET_STATE_PATH = Path(
    os.environ.get("PHYSIOLIVE_STATE_DIR", "/var/lib/physiolive")
) / "jwt.secret"


def _get_or_create_secret() -> bytes:
    """Return the HS256 signing key.

    Preference order:
      1. `PHYSIOLIVE_JWT_SECRET` env var.
      2. Cached secret at `PHYSIOLIVE_STATE_DIR/jwt.secret`.
      3. Freshly generated 512-bit secret written back to (2).

    Rotating the file (or env var) invalidates every issued token,
    which is what you want after a credential compromise.
    """
    env = os.environ.get("PHYSIOLIVE_JWT_SECRET")
    if env:
        return env.encode()
    try:
        if _SECRET_STATE_PATH.exists():
            return _SECRET_STATE_PATH.read_bytes()
    except Exception:
        pass
    fresh = secrets.token_bytes(64)
    try:
        _SECRET_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SECRET_STATE_PATH.write_bytes(fresh)
        os.chmod(_SECRET_STATE_PATH, 0o600)
    except Exception as e:
        print(f"auth: could not persist jwt secret: {e}. Tokens will "
              f"invalidate on next restart.")
    return fresh


def _allowed_emails() -> Set[str]:
    raw = os.environ.get("PHYSIOLIVE_ALLOWED_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def _google_audience() -> Optional[str]:
    return os.environ.get("GOOGLE_OAUTH_CLIENT_ID")


# ------------------------------------------------------------------ helpers

def _stable_sub(email: str, source: str) -> str:
    """Turn an email into a stable, non-guessable user id.

    Using `sha256(secret + email + source)[:24]` means every install
    gets its own namespace and the raw email is not exposed downstream
    to logs or the frontend.
    """
    h = hashlib.sha256()
    h.update(_get_or_create_secret())
    h.update(b"|")
    h.update(source.encode())
    h.update(b"|")
    h.update(email.lower().encode())
    return "u_" + h.hexdigest()[:24]


def _issue_jwt(sub: str, email: str, name: str, source: str) -> Dict:
    now = int(time.time())
    exp = now + _JWT_TTL_SECONDS
    claims = {
        "sub": sub,
        "email": email,
        "name": name,
        "source": source,
        "iat": now,
        "exp": exp,
    }
    token = pyjwt.encode(claims, _get_or_create_secret(), algorithm=_JWT_ALG)
    return {
        "jwt": token,
        "exp": exp,
        "profile": {
            "sub": sub,
            "email": email,
            "name": name,
            "picture": None,
            "source": source,
            "display_name": name,
        },
    }


# ------------------------------------------------------------------ passphrase

def _passphrase_matches(candidate: str) -> bool:
    """Compare `candidate` against the stored bcrypt hash.

    Two shapes accepted for `PHYSIOLIVE_PASSPHRASE`:
      * bcrypt hash starting with `$2a$` / `$2b$` / `$2y$` - preferred.
      * plain string - hashed on the fly, useful for the first-boot
        install script. The install script should replace it with the
        bcrypt hash on next deploy.

    Returns False when neither variable is set (locking the endpoint).
    """
    hashed = os.environ.get("PHYSIOLIVE_PASSPHRASE_HASH", "").strip()
    if hashed:
        try:
            return bcrypt.checkpw(candidate.encode(), hashed.encode())
        except Exception:
            return False
    plain = os.environ.get("PHYSIOLIVE_PASSPHRASE", "").strip()
    if plain:
        return secrets.compare_digest(candidate, plain)
    return False


def issue_passphrase_token(passphrase: str, display_name: str = "") -> Dict:
    if not _passphrase_matches(passphrase):
        raise HTTPException(status_code=401, detail="invalid passphrase")
    display_name = (display_name or "Athlete").strip()[:40] or "Athlete"
    sub = _stable_sub(f"passphrase:{display_name}", "passphrase")
    return _issue_jwt(sub, email="", name=display_name, source="passphrase")


# ------------------------------------------------------------------ google

_GOOGLE_TOKENINFO = "https://oauth2.googleapis.com/tokeninfo"


def issue_google_token(id_token: str) -> Dict:
    """Verify a Google ID token and return a PhysioLive JWT.

    We hit Google's `tokeninfo` endpoint rather than pull in the full
    google-auth library. The endpoint validates the signature, expiry
    and issuer for us. We then check audience (must match
    `GOOGLE_OAUTH_CLIENT_ID` when set) and the email whitelist.
    """
    if not id_token:
        raise HTTPException(status_code=400, detail="missing id_token")
    try:
        resp = httpx.get(_GOOGLE_TOKENINFO,
                         params={"id_token": id_token},
                         timeout=6.0)
    except Exception:
        raise HTTPException(status_code=502, detail="google unreachable")
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="google token rejected")
    data = resp.json()
    aud_expected = _google_audience()
    if aud_expected and data.get("aud") != aud_expected:
        raise HTTPException(status_code=401, detail="wrong audience")
    email = (data.get("email") or "").lower()
    if not email or data.get("email_verified") not in ("true", True):
        raise HTTPException(status_code=401, detail="email not verified")
    allowed = _allowed_emails()
    if allowed and email not in allowed:
        raise HTTPException(status_code=403, detail="email not on allow list")
    name = data.get("name") or email.split("@", 1)[0]
    sub = _stable_sub(email, "google")
    out = _issue_jwt(sub, email=email, name=name, source="google")
    out["profile"]["picture"] = data.get("picture")
    return out


# ------------------------------------------------------------------ verify

def require_auth(
    authorization: Optional[str] = Header(default=None),
) -> Dict:
    """FastAPI dependency that decodes the Bearer JWT.

    Returns the decoded claim set, so route handlers can read
    `user["sub"]` for per-user rate limiting or session logging.
    Raises 401 on any failure - missing header, wrong scheme, expired,
    bad signature.

    When `PHYSIOLIVE_AUTH_DISABLED=1` is set the check is bypassed and
    a synthetic anonymous claim set is returned. Useful only for local
    smoke tests; never set on the live VM.
    """
    if os.environ.get("PHYSIOLIVE_AUTH_DISABLED") == "1":
        return {"sub": "u_local", "email": "", "name": "local",
                "source": "disabled"}
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization[7:].strip()
    try:
        claims = pyjwt.decode(token, _get_or_create_secret(),
                              algorithms=[_JWT_ALG])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token expired")
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid token")
    return claims
