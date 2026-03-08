"""Pydantic models for Evaluation API request and response payloads."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel
from yalc import LLMModel


# ---------------------------------------------------------------------------
# Auth / discovery
# ---------------------------------------------------------------------------


class WellKnown(BaseModel):
    """Response from ``GET /.well-known``."""

    issuer: str


class TokenResponse(BaseModel):
    """Response from ``POST {issuer}/oauth/v2/token``."""

    access_token: str
    id_token: str
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


class CreateEvaluationRequest(BaseModel):
    """Request body for ``POST /v1/app/{id}/evaluation``."""

    app_version: str
    evaluation_type: EvaluationType
    app_answers: dict[str, str]
    llm_judge_models: list[LLMModel]
