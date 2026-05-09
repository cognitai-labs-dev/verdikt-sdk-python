import json

import httpx
import pytest
from yalc import LLMModel

from verdikt_sdk import AnswerWithCost, EvaluationType, VerdiktClient


def _build_handler(captured: dict) -> httpx.MockTransport:
    """Mock transport that fakes the auth + datasets + evaluation endpoints.

    Captures the evaluation POST body in *captured* so tests can assert it.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/.well-known"):
            return httpx.Response(200, json={"issuer": "http://issuer.test"})
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
        if url.endswith("/v1/app/7/evaluation") and request.method == "POST":
            captured["body"] = json.loads(request.content)
            return httpx.Response(201)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_run_evaluation_posts_answers_with_cost_per_dataset_id():
    # Arrange
    captured: dict = {}
    client = VerdiktClient(
        base_url="http://verdikt.test",
        client_id="cid",
        client_secret="csec",
    )
    client._http = httpx.AsyncClient(transport=_build_handler(captured))
    client._auth._http = client._http

    async def callback(question: str) -> AnswerWithCost:
        return AnswerWithCost(
            answer=f"answer-for-{question}",
            cost=0.5 if question == "Q1" else 1.25,
        )

    # Act
    await client.run_evaluation(
        app_slug="my-app",
        app_version="v1.0.0",
        callback=callback,
        evaluation_type=EvaluationType.LLM_ONLY,
        llm_judge_models=[LLMModel.gpt_4o_mini],
    )

    # Assert
    assert captured["body"]["app_answers"] == {
        "11": {"answer": "answer-for-Q1", "cost": 0.5},
        "12": {"answer": "answer-for-Q2", "cost": 1.25},
    }


@pytest.mark.asyncio
async def test_run_evaluation_serializes_null_cost_when_callback_omits_it():
    # Arrange
    captured: dict = {}
    client = VerdiktClient(
        base_url="http://verdikt.test",
        client_id="cid",
        client_secret="csec",
    )
    client._http = httpx.AsyncClient(transport=_build_handler(captured))
    client._auth._http = client._http

    async def callback(question: str) -> AnswerWithCost:
        return AnswerWithCost(answer=f"answer-for-{question}")

    # Act
    await client.run_evaluation(
        app_slug="my-app",
        app_version="v1.0.0",
        callback=callback,
        evaluation_type=EvaluationType.LLM_ONLY,
        llm_judge_models=[LLMModel.gpt_4o_mini],
    )

    # Assert
    assert captured["body"]["app_answers"] == {
        "11": {"answer": "answer-for-Q1", "cost": None},
        "12": {"answer": "answer-for-Q2", "cost": None},
    }
