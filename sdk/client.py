"""Evaluation SDK client."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Callable, Coroutine

import httpx
from yalc import LLMModel

from sdk.auth import TokenAuth
from sdk.http import raise_for_status
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

logger = logging.getLogger(__name__)


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

        self._http = httpx.AsyncClient()
        self._auth = TokenAuth(
            base_url=self.base_url,
            client_id=client_id,
            client_secret=client_secret,
            http=self._http,
        )
        self._slug_cache: dict[str, int] = {}

    async def _resolve_slug(self, app_slug: str) -> int:
        """Return the app_id for *app_slug*, hitting the API only on first call."""
        if app_slug in self._slug_cache:
            return self._slug_cache[app_slug]
        logger.debug("Resolving slug '%s'", app_slug)
        headers = await self._auth.headers()
        resp = await self._http.get(
            f"{self.base_url}/v1/app/by-slug/{app_slug}",
            headers=headers,
        )
        raise_for_status(resp)
        app_id = AppResponse.model_validate(resp.json()).id
        self._slug_cache[app_slug] = app_id
        logger.debug("Resolved slug '%s' -> app_id %d", app_slug, app_id)
        return app_id

    async def create_app(self, slug: str, name: str) -> None:
        """Idempotent — safe to call on every deploy.

        Checks whether the app already exists by slug; creates it only when it
        does not.

        Args:
            slug: URL-safe identifier for the app (lowercase, hyphens only).
            name: Human-readable display name.
        """
        logger.info("Ensuring app '%s' exists", slug)
        headers = await self._auth.headers()
        resp = await self._http.get(
            f"{self.base_url}/v1/app/by-slug/{slug}",
            headers=headers,
        )
        if resp.status_code == 200:
            logger.info("App '%s' already exists, skipping creation", slug)
            return
        if resp.status_code != 404:
            raise_for_status(resp)

        logger.info("Creating app '%s' (%s)", slug, name)
        body = CreateAppRequest(slug=slug, name=name)
        create_resp = await self._http.post(
            f"{self.base_url}/v1/app",
            json=body.model_dump(),
            headers=headers,
        )
        raise_for_status(create_resp)
        logger.info("App '%s' created", slug)

    async def add_questions(
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
        app_id = await self._resolve_slug(app_slug)
        logger.info("Syncing %d question(s) for app '%s'", len(questions), app_slug)

        headers = await self._auth.headers()
        hashes_resp = await self._http.get(
            f"{self.base_url}/v1/app/{app_id}/datasets/hashes",
            headers=headers,
        )
        raise_for_status(hashes_resp)
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
                logger.info("Adding new question: '%s'", q.question)
                body = CreateDatasetRequest(
                    question=q.question, human_answer=q.human_answer
                )
                raise_for_status(
                    await self._http.post(
                        f"{self.base_url}/v1/app/{app_id}/datasets",
                        json=body.model_dump(),
                        headers=headers,
                    )
                )
            elif existing_by_q_hash[q_hash].human_answer_hash != a_hash:
                dataset_id = existing_by_q_hash[q_hash].id
                logger.info("Updating answer for question: '%s'", q.question)
                patch_body = UpdateDatasetRequest(human_answer=q.human_answer)
                raise_for_status(
                    await self._http.patch(
                        f"{self.base_url}/v1/app/{app_id}/datasets/{dataset_id}",
                        json=patch_body.model_dump(),
                        headers=headers,
                    )
                )
            else:
                logger.debug("Question unchanged, skipping: '%s'", q.question)

    async def run_evaluation(
        self,
        app_slug: str,
        app_version: str,
        callback: Callable[[str], Coroutine[None, None, str]],
        evaluation_type: EvaluationType,
        llm_judge_models: list[LLMModel],
    ) -> None:
        """Run an evaluation cycle against all dataset questions.

        All callback invocations run concurrently as asyncio tasks.

        Args:
            app_slug: Slug of the target app.
            app_version: Semantic version string identifying this build.
            callback: Async function that receives a question string and returns
                an answer string.
            evaluation_type: Whether to use LLM scoring only or both human and
                LLM scoring.
            llm_judge_models: List of model identifiers to use as judges.
        """
        app_id = await self._resolve_slug(app_slug)
        logger.info(
            "Running evaluation for app '%s' version '%s'", app_slug, app_version
        )

        headers = await self._auth.headers()
        datasets_resp = await self._http.get(
            f"{self.base_url}/v1/app/{app_id}/datasets",
            headers=headers,
        )
        raise_for_status(datasets_resp)
        datasets = [DatasetEntry.model_validate(item) for item in datasets_resp.json()]
        logger.info(
            "Collected %d question(s), invoking callbacks concurrently", len(datasets)
        )

        answers = await asyncio.gather(*[callback(item.question) for item in datasets])
        app_answers = {str(item.id): answer for item, answer in zip(datasets, answers)}

        body = CreateEvaluationRequest(
            app_version=app_version,
            evaluation_type=evaluation_type,
            app_answers=app_answers,
            llm_judge_models=llm_judge_models,
        )
        raise_for_status(
            await self._http.post(
                f"{self.base_url}/v1/app/{app_id}/evaluation",
                json=body.model_dump(),
                headers=headers,
            )
        )
        logger.info(
            "Evaluation submitted for app '%s' version '%s'", app_slug, app_version
        )
