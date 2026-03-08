"""OAuth2 client-credentials auth for the Evaluation SDK."""

from __future__ import annotations

import httpx
from cachetools import TTLCache, cachedmethod

from sdk.models import TokenResponse, WellKnown


class TokenAuth:
    """Handles Zitadel OAuth2 client-credentials token discovery and caching.

    Args:
        base_url: Base URL of the evaluation service (used to discover the issuer).
        client_id: Zitadel machine user client ID.
        client_secret: Zitadel machine user client secret.
        http: Shared ``httpx.Client`` instance.
    """

    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        http: httpx.Client,
    ) -> None:
        self._base_url = base_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http

        self._issuer_cache: TTLCache[str, str] = TTLCache(maxsize=1, ttl=86400)
        self._token_cache: TTLCache[str, str] = TTLCache(maxsize=1, ttl=3570)

    @cachedmethod(lambda self: self._issuer_cache)
    def _discover_issuer(self) -> str:
        resp = self._http.get(f"{self._base_url}/.well-known")
        resp.raise_for_status()
        return WellKnown.model_validate(resp.json()).issuer

    @cachedmethod(lambda self: self._token_cache)
    def _fetch_token(self) -> str:
        resp = self._http.post(
            f"{self._discover_issuer()}/oauth/v2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        resp.raise_for_status()
        return TokenResponse.model_validate(resp.json()).access_token

    def token(self) -> str:
        """Return a valid bearer token, refreshing automatically when expired."""
        return self._fetch_token()

    def headers(self) -> dict[str, str]:
        """Return an ``Authorization`` header dict ready for use in requests."""
        return {"Authorization": f"Bearer {self.token()}"}
