"""Authentication for protected analyst/dashboard API routes."""
from __future__ import annotations

import hmac
import logging
import os
from typing import Any, Dict, Optional

import httpx
import jwt
from fastapi import HTTPException, Request

logger = logging.getLogger("blue.auth")


def get_bearer_token(request: Request) -> Optional[str]:
    auth_header = request.headers.get("Authorization", "").strip()
    scheme, separator, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        return None
    return token.strip()


def verify_dashboard_token(token: str) -> Dict[str, Any]:
    if not token:
        raise HTTPException(status_code=401, detail="Authentication token required.")

    for name in ("INGEST_API_TOKEN", "SUPABASE_SECRET_KEY", "DASHBOARD_API_KEY"):
        expected = os.getenv(name, "").strip()
        if expected and hmac.compare_digest(expected, token):
            return {"sub": "service_role", "role": "service_role"}

    jwt_secret = os.getenv("SUPABASE_JWT_SECRET", "").strip() or os.getenv("SUPABASE_SECRET_KEY", "").strip()
    if jwt_secret:
        try:
            return jwt.decode(
                token,
                jwt_secret,
                algorithms=["HS256"],
                options={"verify_aud": False, "verify_signature": True},
            )
        except jwt.PyJWTError:
            pass

    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    if supabase_url:
        try:
            api_key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
            if not api_key:
                api_key = os.getenv("SUPABASE_SECRET_KEY", "").strip()
            headers = {"Authorization": f"Bearer {token}"}
            if api_key:
                headers["apikey"] = api_key
            response = httpx.get(
                f"{supabase_url.rstrip('/')}/auth/v1/user",
                headers=headers,
                timeout=5.0,
            )
            if response.status_code == 200:
                user = response.json()
                return {"sub": user.get("id"), "email": user.get("email"), "role": "authenticated"}
        except Exception as exc:
            logger.warning("Supabase auth verification failed (%s).", type(exc).__name__)

    raise HTTPException(status_code=401, detail="Invalid or expired authentication credentials.")


def require_dashboard_auth(request: Request) -> Dict[str, Any]:
    token = get_bearer_token(request)
    if not token:
        is_deployed = bool(
            os.getenv("FLY_APP_NAME")
            or os.getenv("RAILWAY_ENVIRONMENT")
            or os.getenv("PRODUCTION", "").lower() in {"true", "1"}
        )
        auth_configured = any(
            os.getenv(name, "").strip()
            for name in ("INGEST_API_TOKEN", "SUPABASE_SECRET_KEY", "SUPABASE_URL", "DASHBOARD_API_KEY")
        )
        if is_deployed or auth_configured:
            raise HTTPException(status_code=401, detail="Authentication required to access dashboard data.")
        return {"sub": "dev_anonymous", "role": "dev"}
    return verify_dashboard_token(token)
