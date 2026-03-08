"""Evaluation SDK client."""

from __future__ import annotations

import hashlib
from typing import Callable

import httpx
from cachetools import LRUCache, cachedmethod
from yalc import LLMModel

from sdk.auth import TokenAuth
from sdk.models import (
    AppResponse,
    CreateAppRequest,
    CreateDatasetRequest,
    CreateEvaluationRequest,
    DatasetEntry,
    DatasetHashEntry,
    EvaluationType,
    Question,
    UpdateDatasetRequest,
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.strip().encode()).hexdigest()


class EvaluationClient:
    """Python SDK for the Evaluation API.

    Handles OAuth2 authentication, dataset diffing, and evaluation submission.

    Args:
        base_url: Base URL of the evaluation service, e.g. ``"https://eval.mycompany.com"``.
        client_id: Zitadel machine user client ID.
        client_secret: Zitadel machine user client secret.
    """

    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        self.base_url = base_url.rstrip("/")

        self._http = httpx.Client()
        self._auth = TokenAuth(
            base_url=self.base_url,
            client_id=client_id,
            client_secret=client_secret,
            http=self._http,
        )
        self._slug_cache: LRUCache[str, int] = LRUCache(maxsize=256)

    @cachedmethod(lambda self: self._slug_cache)
    def _resolve_slug(self, app_slug: str) -> int:
        """Return the app_id for *app_slug*, hitting the API only on first call."""
        resp = self._http.get(
            f"{self.base_url}/v1/app/by-slug/{app_slug}",
            headers=self._auth.headers(),
        )
        resp.raise_for_status()
        return AppResponse.model_validate(resp.json()).id

    def create_app(self, slug: str, name: str) -> None:
        """Idempotent — safe to call on every deploy.

        Checks whether the app already exists by slug; creates it only when it
        does not.

        Args:
            slug: URL-safe identifier for the app (lowercase, hyphens only).
            name: Human-readable display name.
        """
        resp = self._http.get(
            f"{self.base_url}/v1/app/by-slug/{slug}",
            headers=self._auth.headers(),
        )
        if resp.status_code == 200:
            return
        if resp.status_code != 404:
            resp.raise_for_status()

        body = CreateAppRequest(slug=slug, name=name)
        create_resp = self._http.post(
            f"{self.base_url}/v1/app",
            json=body.model_dump(),
            headers=self._auth.headers(),
        )
        create_resp.raise_for_status()

    def add_questions(
        self,
        app_slug: str,
        questions: list[Question],
    ) -> None:
        """Idempotent — safe to call on every deploy.

        Syncs *questions* to the remote dataset using SHA-256 diffing so that
        only new or changed entries are written.

        Args:
            app_slug: Slug of the target app.
            questions: List of questions with their expected human answers.
        """
        app_id = self._resolve_slug(app_slug)

        hashes_resp = self._http.get(
            f"{self.base_url}/v1/app/{app_id}/datasets/hashes",
            headers=self._auth.headers(),
        )
        hashes_resp.raise_for_status()
        existing = [
            DatasetHashEntry.model_validate(entry) for entry in hashes_resp.json()
        ]

        existing_by_q_hash: dict[str, DatasetHashEntry] = {
            entry.question_hash: entry for entry in existing
        }

        for q in questions:
            q_hash = _sha256(q.question)
            a_hash = _sha256(q.human_answer)

            if q_hash not in existing_by_q_hash:
                body = CreateDatasetRequest(
                    question=q.question, human_answer=q.human_answer
                )
                self._http.post(
                    f"{self.base_url}/v1/app/{app_id}/datasets",
                    json=body.model_dump(),
                    headers=self._auth.headers(),
                ).raise_for_status()
            elif existing_by_q_hash[q_hash].human_answer_hash != a_hash:
                dataset_id = existing_by_q_hash[q_hash].id
                patch_body = UpdateDatasetRequest(human_answer=q.human_answer)
                self._http.patch(
                    f"{self.base_url}/v1/app/{app_id}/datasets/{dataset_id}",
                    json=patch_body.model_dump(),
                    headers=self._auth.headers(),
                ).raise_for_status()

    def run_evaluation(
        self,
        app_slug: str,
        app_version: str,
        callback: Callable[[str], str],
        evaluation_type: EvaluationType,
        llm_judge_models: list[LLMModel],
    ) -> None:
        """Run an evaluation cycle against all dataset questions.

        Fetches every question in the app's dataset, passes each one to
        *callback*, then submits all answers in a single evaluation request.

        Args:
            app_slug: Slug of the target app.
            app_version: Semantic version string identifying this build.
            callback: Function that receives a question string and returns an
                answer string.
            evaluation_type: Whether to use LLM scoring only or both human and
                LLM scoring.
            llm_judge_models: List of model identifiers to use as judges.
                Defaults to ``["gpt-4o-mini"]`` when *None*.
        """
        app_id = self._resolve_slug(app_slug)

        datasets_resp = self._http.get(
            f"{self.base_url}/v1/app/{app_id}/datasets",
            headers=self._auth.headers(),
        )
        datasets_resp.raise_for_status()
        datasets = [DatasetEntry.model_validate(item) for item in datasets_resp.json()]

        app_answers: dict[str, str] = {
            str(item.id): callback(item.question) for item in datasets
        }

        body = CreateEvaluationRequest(
            app_version=app_version,
            evaluation_type=evaluation_type,
            app_answers=app_answers,
            llm_judge_models=llm_judge_models,
        )
        self._http.post(
            f"{self.base_url}/v1/app/{app_id}/evaluation",
            json=body.model_dump(),
            headers=self._auth.headers(),
        ).raise_for_status()
