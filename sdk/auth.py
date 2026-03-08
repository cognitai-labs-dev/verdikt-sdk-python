"""OAuth2 client-credentials auth for the Evaluation SDK."""

from __future__ import annotations

import logging
import time

import httpx

from sdk.http import raise_for_status
from sdk.models import TokenResponse, WellKnown

logger = logging.getLogger(__name__)


class TokenAuth:
    """Handles Zitadel OAuth2 client-credentials token discovery and caching.

    Args:
        base_url: Base URL of the evaluation service (used to discover the issuer).
        client_id: Zitadel machine user client ID.
        client_secret: Zitadel machine user client secret.
        http: Shared ``httpx.AsyncClient`` instance.
    """

    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        http: httpx.AsyncClient,
    ) -> None:
        self._base_url = base_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http

        self._issuer: str | None = None
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._issuer_expires_at: float = 0.0

    async def _discover_issuer(self) -> str:
        if self._issuer is not None and time.monotonic() < self._issuer_expires_at:
            return self._issuer
        logger.debug("Fetching issuer from %s/.well-known", self._base_url)
        resp = await self._http.get(f"{self._base_url}/.well-known")
        raise_for_status(resp)
        self._issuer = WellKnown.model_validate(resp.json()).issuer
        self._issuer_expires_at = time.monotonic() + 86400
        logger.debug("Discovered issuer: %s", self._issuer)
        return self._issuer

    async def _fetch_token(self) -> str:
        logger.debug("Fetching new access token")
        resp = await self._http.post(
            f"{await self._discover_issuer()}/oauth/v2/token",
            data={
                "grant_type": "client_credentials",
                "scope": "openid profile",
            },
            auth=(self._client_id, self._client_secret),
        )
        raise_for_status(resp)
        token_resp = TokenResponse.model_validate(resp.json())
        self._token = token_resp.access_token
        self._token_expires_at = time.monotonic() + token_resp.expires_in - 30
        logger.debug("Access token acquired, expires in %ds", token_resp.expires_in)
        return token_resp.access_token

    async def token(self) -> str:
        """Return a valid bearer token, refreshing automatically when expired."""
        if self._token is not None and time.monotonic() < self._token_expires_at:
            return self._token
        return await self._fetch_token()

    async def headers(self) -> dict[str, str]:
        """Return an ``Authorization`` header dict ready for use in requests."""
        return {"Authorization": f"Bearer {await self.token()}"}
