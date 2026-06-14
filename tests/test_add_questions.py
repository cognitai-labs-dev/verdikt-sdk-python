import json

import httpx
import pytest

from verdikt_sdk import VerdiktClient
from verdikt_sdk.models import Question


def _build_handler(captured: dict) -> httpx.MockTransport:
    """Mock transport faking auth + datasets GET/POST/DELETE endpoints.

    Records POSTed body and DELETEd dataset ids in *captured*.
    """
    captured.setdefault("deleted_ids", [])

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/.well-known"):
            return httpx.Response(200, json={"issuer": "http://issuer.test"})
        if url.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={"token_endpoint": "http://issuer.test/oauth/v2/token"},
            )
        if "/oauth/v2/token" in url:
            return httpx.Response(
                200,
                json={
                    "access_token": "tok",
                    "id_token": "id",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                },
            )
        if "/v1/app/by-slug/" in url:
            return httpx.Response(
                200, json={"id": 7, "slug": "my-app", "name": "My App"}
            )
        if url.endswith("/v1/app/7/datasets") and request.method == "GET":
            return httpx.Response(
                200,
                json=[
                    {"id": 11, "question": "Q1", "human_answer": "A1"},
                    {"id": 12, "question": "Q2", "human_answer": "A2"},
                ],
            )
        if url.endswith("/v1/app/7/datasets") and request.method == "POST":
            captured["posted"] = json.loads(request.content)
            return httpx.Response(201, json=[])
        if "/v1/app/7/datasets/" in url and request.method == "DELETE":
            captured["deleted_ids"].append(int(url.rsplit("/", 1)[1]))
            return httpx.Response(204)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _make_client(captured: dict) -> VerdiktClient:
    client = VerdiktClient(
        base_url="http://verdikt.test",
        client_id="cid",
        client_secret="csec",
    )
    client._http = httpx.AsyncClient(transport=_build_handler(captured))
    client._auth._http = client._http
    return client


@pytest.mark.asyncio
async def test_add_questions_delete_old_deletes_unprovided_questions():
    # Arrange
    captured: dict = {}
    client = _make_client(captured)

    # Act — existing is [Q1, Q2]; provide Q1 (overlap) + Qnew
    await client.add_questions(
        app_slug="my-app",
        questions=[
            Question(question="Q1", human_answer="A1"),
            Question(question="Qnew", human_answer="Anew"),
        ],
        delete_old=True,
    )

    # Assert — only Q2 (id 12) is unprovided, so only it is deleted
    assert captured["deleted_ids"] == [12]


@pytest.mark.asyncio
async def test_add_questions_delete_old_raises_when_all_would_be_deleted():
    # Arrange
    captured: dict = {}
    client = _make_client(captured)

    # Act / Assert — no overlap with existing [Q1, Q2] => full wipe => refused
    with pytest.raises(ValueError):
        await client.add_questions(
            app_slug="my-app",
            questions=[Question(question="Qx", human_answer="Ax")],
            delete_old=True,
        )

    # Nothing was posted or deleted
    assert captured["deleted_ids"] == []
    assert "posted" not in captured


@pytest.mark.asyncio
async def test_add_questions_without_delete_old_does_not_delete():
    # Arrange
    captured: dict = {}
    client = _make_client(captured)

    # Act
    await client.add_questions(
        app_slug="my-app",
        questions=[Question(question="Qx", human_answer="Ax")],
    )

    # Assert — default leaves existing questions untouched
    assert captured["deleted_ids"] == []
    assert captured["posted"]["datasets"] == [
        {"question": "Qx", "human_answer": "Ax"}
    ]
