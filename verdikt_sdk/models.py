"""Pydantic models for Evaluation API request and response payloads."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel
from yalc import LLMModel


# ---------------------------------------------------------------------------
# Auth / discovery
# ---------------------------------------------------------------------------


class OpenIDConfiguration(BaseModel):
    """Subset of ``GET {base_url}/.well-known/openid-configuration``."""

    token_endpoint: str


class TokenResponse(BaseModel):
    """Response from ``POST {token_endpoint}`` (the IdP token endpoint).

    ``id_token`` is optional — not every provider returns one for the
    client-credentials grant.
    """

    access_token: str
    id_token: str | None = None
    token_type: str
    expires_in: int


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


class AppResponse(BaseModel):
    """Response from ``GET /v1/app/by-slug/{slug}`` and ``POST /v1/app``."""

    id: int
    slug: str
    name: str


class CreateAppRequest(BaseModel):
    """Request body for ``POST /v1/app``."""

    slug: str
    name: str


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------


class DatasetHashEntry(BaseModel):
    """One entry from ``GET /v1/app/{id}/datasets/hashes``."""

    id: int
    question_hash: str
    human_answer_hash: str


class DatasetEntry(BaseModel):
    """One entry from ``GET /v1/app/{id}/datasets``."""

    id: int
    question: str
    human_answer: str


class Question(BaseModel):
    """A question/answer pair passed to ``add_questions``."""

    question: str
    human_answer: str


class CreateDatasetRequest(BaseModel):
    """Request body for ``POST /v1/app/{id}/datasets``."""

    question: str
    human_answer: str


class UpdateDatasetRequest(BaseModel):
    """Request body for ``PATCH /v1/app/{id}/datasets/{dataset_id}``."""

    human_answer: str


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


class EvaluationType(StrEnum):
    LLM_ONLY = "LLM_ONLY"
    HUMAN_AND_LLM = "HUMAN_AND_LLM"


class AnswerWithCost(BaseModel):
    """Answer plus the cost incurred producing it.

    Returned by ``run_evaluation`` callbacks. ``cost`` is optional — pass
    ``None`` (or omit) when cost tracking is not relevant.
    """

    answer: str
    cost: float | None = None


class CreateEvaluationRequest(BaseModel):
    """Request body for ``POST /v1/app/{id}/evaluation``."""

    app_version: str
    evaluation_type: EvaluationType
    app_answers: dict[str, AnswerWithCost]
    llm_judge_models: list[LLMModel]
