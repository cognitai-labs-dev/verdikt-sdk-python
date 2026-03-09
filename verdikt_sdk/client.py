"""Verdikt SDK client."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Coroutine

import httpx
from yalc import LLMModel

from verdikt_sdk.auth import TokenAuth
from verdikt_sdk.http import raise_for_status
from verdikt_sdk.models import (
    AppResponse,
    CreateAppRequest,
    CreateDatasetRequest,
    CreateEvaluationRequest,
    DatasetEntry,
    EvaluationType,
    Question,
)

logger = logging.getLogger(__name__)


class VerdiktClient:
    """Python SDK for the Verdikt Evaluation API.

    Handles OAuth2 authentication, dataset syncing, and evaluation submission.

    Args:
        base_url: Base URL of the Verdikt service, e.g. ``"https://verdikt.mycompany.com"``.
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
        if slug in self._slug_cache:
            logger.info("App '%s' already exists, skipping creation", slug)
            return

        headers = await self._auth.headers()
        resp = await self._http.get(
            f"{self.base_url}/v1/app/by-slug/{slug}",
            headers=headers,
        )
        if resp.status_code == 200:
            logger.info("App '%s' already exists, skipping creation", slug)
            self._slug_cache[slug] = AppResponse.model_validate(resp.json()).id
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
        self._slug_cache[slug] = AppResponse.model_validate(create_resp.json()).id
        logger.info("App '%s' created", slug)

    async def add_questions(
        self,
        app_slug: str,
        questions: list[Question],
    ) -> None:
        """Idempotent — safe to call on every deploy.

        Syncs *questions* to the remote dataset.

        Args:
            app_slug: Slug of the target app.
            questions: List of questions with their expected human answers.
        """
        app_id = await self._resolve_slug(app_slug)
        logger.info("Syncing %d question(s) for app '%s'", len(questions), app_slug)

        headers = await self._auth.headers()
        hashes_resp = await self._http.post(
            f"{self.base_url}/v1/app/{app_id}/datasets",
            json={
                "datasets": [
                    CreateDatasetRequest(**q.model_dump()).model_dump()
                    for q in questions
                ]
            },
            headers=headers,
        )
        raise_for_status(hashes_resp)

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
