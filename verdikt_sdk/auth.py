"""OAuth2 client-credentials auth for the Evaluation SDK."""

from __future__ import annotations

import logging
import time

import httpx

from verdikt_sdk.http import raise_for_status
from verdikt_sdk.models import OpenIDConfiguration, TokenResponse, WellKnown

logger = logging.getLogger(__name__)

_DISCOVERY_TTL = 86400


class TokenAuth:
    """OAuth2 client-credentials token acquisition against any OIDC provider.

    The token endpoint is discovered from the provider's standard
    ``/.well-known/openid-configuration`` document, so this works with any
    OIDC-compliant IdP (Zitadel, Keycloak, Okta, Auth0, ...) — not just Zitadel.

    Args:
        base_url: Base URL of the evaluation service (used to discover the issuer).
        client_id: Machine/service-account client ID registered in the IdP.
        client_secret: The matching client secret.
        http: Shared ``httpx.AsyncClient`` instance.
        audience: Optional ``audience`` to request, so the issued token's ``aud``
            matches what the Verdikt backend verifies (``OIDC_AUDIENCE``). Sent
            as the ``audience`` token-request parameter when set.
        scope: OAuth scopes to request. Defaults to ``"openid profile"``.
    """

    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        http: httpx.AsyncClient,
        audience: str | None = None,
        scope: str = "openid profile",
    ) -> None:
        self._base_url = base_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http
        self._audience = audience
        self._scope = scope

        self._issuer: str | None = None
        self._token_endpoint: str | None = None
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._discovery_expires_at: float = 0.0

    async def _discover_issuer(self) -> str:
        if self._issuer is not None and time.monotonic() < self._discovery_expires_at:
            return self._issuer
        logger.debug("Fetching issuer from %s/.well-known", self._base_url)
        resp = await self._http.get(f"{self._base_url}/.well-known")
        raise_for_status(resp)
        self._issuer = WellKnown.model_validate(resp.json()).issuer
        logger.debug("Discovered issuer: %s", self._issuer)
        return self._issuer

    async def _discover_token_endpoint(self) -> str:
        if (
            self._token_endpoint is not None
            and time.monotonic() < self._discovery_expires_at
        ):
            return self._token_endpoint
        issuer = await self._discover_issuer()
        url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
        logger.debug("Fetching OIDC configuration from %s", url)
        resp = await self._http.get(url)
        raise_for_status(resp)
        self._token_endpoint = OpenIDConfiguration.model_validate(
            resp.json()
        ).token_endpoint
        self._discovery_expires_at = time.monotonic() + _DISCOVERY_TTL
        logger.debug("Discovered token endpoint: %s", self._token_endpoint)
        return self._token_endpoint

    async def _fetch_token(self) -> str:
        logger.debug("Fetching new access token")
        data = {
            "grant_type": "client_credentials",
            "scope": self._scope,
        }
        if self._audience is not None:
            data["audience"] = self._audience
        resp = await self._http.post(
            await self._discover_token_endpoint(),
            data=data,
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
