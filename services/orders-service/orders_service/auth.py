"""Cognito ID token verification (replaces API Gateway's Cognito authorizer from Project 3).

The token is verified locally: RS256 signature against the user pool's JWKS (fetched once and
cached), issuer, audience (= app client id), token_use = "id" and expiry. The customer id is the
verified `sub` claim - never something from the request body.
"""
import jwt
from fastapi import Header, HTTPException

from .config import Settings


class TokenVerifier:
    def __init__(self, settings: Settings):
        self._settings = settings
        # PyJWKClient caches the keys and re-fetches only for an unknown `kid` (key rotation)
        self._jwks = jwt.PyJWKClient(settings.jwks_url, cache_keys=True, lifespan=3600, timeout=5)

    def verify(self, token: str) -> dict:
        try:
            key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token, key.key, algorithms=["RS256"],
                audience=self._settings.app_client_id, issuer=self._settings.issuer,
                options={"require": ["exp", "iat", "sub", "token_use"]},
            )
        except jwt.PyJWKClientConnectionError as err:
            raise HTTPException(status_code=503, detail="token keys unavailable") from err
        except jwt.PyJWTError as err:
            raise HTTPException(status_code=401, detail="invalid token") from err
        if claims.get("token_use") != "id":
            raise HTTPException(status_code=401, detail="an ID token is required")
        return claims


def bearer_token(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token",
                            headers={"WWW-Authenticate": "Bearer"})
    return authorization.split(" ", 1)[1].strip()
