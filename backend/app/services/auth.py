from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import jwt
from fastapi import Depends, HTTPException, Request
try:
    from pwdlib import PasswordHash
except Exception:  # optional until auth is enabled
    PasswordHash = None  # type: ignore[assignment]

from .db import User, SessionLocal, init_db
from sqlalchemy import select


def _jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET", "").strip()
    if auth_required() and len(secret) < 32:
        raise RuntimeError("JWT_SECRET must be at least 32 characters when AUTH_REQUIRED=true.")
    return secret or "medaxis-development-only-change-me"


ROLES = {
    "administrator",
    "radiologist",
    "clinician",
    "researcher",
    "biomedical_engineer",
    "technician",
    "viewer",
}

ROLE_LEVELS = {
    "viewer": 10,
    "technician": 20,
    "biomedical_engineer": 30,
    "researcher": 40,
    "clinician": 50,
    "radiologist": 60,
    "administrator": 100,
}

_password_hash = PasswordHash.recommended() if PasswordHash is not None else None


def auth_required() -> bool:
    return os.getenv("AUTH_REQUIRED", "false").strip().lower() in {"1", "true", "yes", "on"}


def jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET", "").strip()
    if auth_required():
        if len(secret) < 32:
            raise RuntimeError("JWT_SECRET must be at least 32 characters when AUTH_REQUIRED=true.")
        return secret
    return secret or "medaxis-local-development-secret-change-this-before-production-32+"


def hash_password(password: str) -> str:
    if _password_hash is None:
        raise RuntimeError("pwdlib is required for password authentication.")
    return _password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    if _password_hash is None:
        return False
    try:
        return _password_hash.verify(password, hashed)
    except Exception:
        return False


def create_token(username: str, role: str, minutes: int | None = None) -> str:
    expire_minutes = minutes or int(os.getenv("JWT_EXPIRE_MINUTES", "480"))
    now = datetime.now(timezone.utc)
    payload = {"sub": username, "role": role, "iat": now, "exp": now + timedelta(minutes=expire_minutes)}
    return jwt.encode(payload, jwt_secret(), algorithm="HS256")


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, jwt_secret(), algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(401, detail={"problem": "Authentication required", "reason": "The access token is missing, invalid, or expired.", "recommended_action": "Sign in again."}) from exc


def authenticate_user(username: str, password: str) -> User | None:
    init_db()
    with SessionLocal() as session:
        user = session.scalars(select(User).where(User.username == username)).first()
        if user is None or not user.active or not verify_password(password, user.password_hash):
            return None
        return user


def current_user_from_request(request: Request) -> dict[str, Any]:
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        if not auth_required():
            return {"username": "local-user", "role": "administrator", "auth_disabled": True}
        raise HTTPException(401, detail={"problem": "Authentication required", "reason": "No bearer token was supplied.", "recommended_action": "Sign in and retry the request."})
    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_token(token)
    username = str(payload.get("sub", "")).strip()
    token_role = str(payload.get("role", "")).strip()
    if not username or token_role not in ROLES:
        raise HTTPException(401, detail={"problem": "Authentication required", "reason": "The token payload is invalid.", "recommended_action": "Sign in again."})
    # The database is authoritative for active status and current role. This
    # prevents an old token from retaining privileges after an administrator
    # changes or disables the account.
    init_db()
    with SessionLocal() as session:
        user = session.scalars(select(User).where(User.username == username)).first()
        if user is None or not user.active or user.role not in ROLES:
            raise HTTPException(401, detail={"problem": "Authentication required", "reason": "The account is unavailable or inactive.", "recommended_action": "Contact an administrator or sign in with an active account."})
        return {"username": user.username, "role": user.role, "auth_disabled": False}


def require_roles(*roles: str):
    allowed = set(roles)
    invalid = allowed - ROLES
    if invalid:
        raise ValueError(f"Unknown roles: {sorted(invalid)}")

    async def dependency(request: Request) -> dict[str, Any]:
        user = current_user_from_request(request)
        if user.get("auth_disabled"):
            return user
        if user["role"] not in allowed:
            raise HTTPException(403, detail={"problem": "Insufficient role", "reason": f"Role '{user['role']}' cannot perform this operation.", "recommended_action": f"Use one of: {', '.join(sorted(allowed))}."})
        return user
    return dependency


def require_min_role(role: str):
    if role not in ROLE_LEVELS:
        raise ValueError(role)

    async def dependency(request: Request) -> dict[str, Any]:
        user = current_user_from_request(request)
        if user.get("auth_disabled"):
            return user
        if ROLE_LEVELS[user["role"]] < ROLE_LEVELS[role]:
            raise HTTPException(403, detail={"problem": "Insufficient role", "reason": f"Role '{user['role']}' is below required role '{role}'.", "recommended_action": "Sign in with an authorized role."})
        return user
    return dependency
