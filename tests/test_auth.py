import httpx
import pytest

from verdikt_sdk import VerdiktClient


def _build_handler(captured: dict) -> httpx.MockTransport:
    """Mock Verdikt discovery + token endpoint, capturing the token request form."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/.well-known/openid-configuration"):
            captured["discovery_url"] = url
            return httpx.Response(
                200,
                json={"token_endpoint": "http://issuer.test/custom/token"},
            )
        if url == "http://issuer.test/custom/token":
            captured["token_url"] = url
            captured["token_form"] = dict(
                httpx.QueryParams(request.content.decode())
            )
            return httpx.Response(
                200,
                json={
                    "access_token": "tok",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                },
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _make_client(captured: dict, **kwargs) -> VerdiktClient:
    client = VerdiktClient(
        base_url="http://verdikt.test",
        client_id="cid",
        client_secret="csec",
        **kwargs,
    )
    client._http = httpx.AsyncClient(transport=_build_handler(captured))
    client._auth._http = client._http
    return client


@pytest.mark.asyncio
async def test_token_endpoint_is_discovered_from_openid_configuration():
    # Arrange
    captured: dict = {}
    client = _make_client(captured)

    # Act
    token = await client._auth.token()

    # Assert — used the discovered endpoint, not a hardcoded path
    assert token == "tok"
    assert captured["discovery_url"] == (
        "http://verdikt.test/.well-known/openid-configuration"
    )
    assert captured["token_url"] == "http://issuer.test/custom/token"


@pytest.mark.asyncio
async def test_audience_is_sent_when_configured():
    # Arrange
    captured: dict = {}
    client = _make_client(captured, audience="verdikt-api")

    # Act
    await client._auth.token()

    # Assert
    assert captured["token_form"]["audience"] == "verdikt-api"


@pytest.mark.asyncio
async def test_audience_is_omitted_when_not_configured():
    # Arrange
    captured: dict = {}
    client = _make_client(captured)

    # Act
    await client._auth.token()

    # Assert
    assert "audience" not in captured["token_form"]
