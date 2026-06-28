# Evaluation SDK Spec

Python SDK that wraps the evaluation API so integrators only provide a callback — the SDK handles auth, dataset diffing, and evaluation submission.

---

## Backend changes required (this repo)

Four additions needed before the SDK can be built:

### 1. Add `slug` to apps

- Add a `slug` column to the `apps` table — unique, not null, URL-safe (lowercase, hyphens)
- Enforced at the DB level with a unique constraint
- `POST /v1/app` accepts `slug` alongside `name`
- New endpoint: `GET /v1/app/by-slug/{slug}` → returns `AppSchema` (404 if not found)

This replaces the need to fetch all apps and filter client-side.

### 2. `GET /.well-known`
Returns the Zitadel issuer URL so the SDK can discover it from `base_url` alone.

```json
{ "issuer": "https://my-zitadel.example.com" }
```

### 3. `GET /v1/app/{app_id}/datasets/hashes`
Lightweight endpoint for SDK diffing — returns hashes only, no full text.

```json
[
  { "id": 1, "question_hash": "sha256...", "human_answer_hash": "sha256..." },
  { "id": 2, "question_hash": "sha256...", "human_answer_hash": "sha256..." }
]
```

Hash algorithm: SHA-256 of the stripped text.

### 4. `PATCH /v1/app/{app_id}/datasets/{dataset_id}`
Updates `human_answer` (and optionally `question`) on an existing dataset entry.
`AppDatasetUpdateSchema` already exists in `src/schemas/app_dataset.py` — just needs a route.

---

## SDK interface

```python
from eval_sdk import EvaluationClient
from typing import Callable, Literal

class EvaluationClient:
    def __init__(
        self,
        base_url: str,       # e.g. "https://eval.mycompany.com"
        client_id: str,      # Zitadel machine user client ID
        client_secret: str,  # Zitadel machine user client secret
    ) -> None: ...

    def add_questions(
        self,
        app_slug: str,
        questions: list[dict],  # [{"question": str, "human_answer": str}]
    ) -> None: ...

    def run_evaluation(
        self,
        app_slug: str,
        app_version: str,
        callback: Callable[[str], str],
        evaluation_type: Literal["LLM_ONLY", "HUMAN_AND_LLM"] = "LLM_ONLY",
        llm_judge_models: list[str] | None = None,
    ) -> None: ...
```

---

## Prerequisite: the app must already exist

The SDK does **not** create apps. A machine client is scoped to the apps it is
bound to and cannot create new ones. Before using the SDK, an admin must create
the app and bind this client to it in the Verdikt admin UI. The SDK then
references the app by its slug.

## Method details

### `add_questions(app_slug, questions)`
Idempotent — safe to call on every deploy. Uses SHA-256 of the question text as the match key so full text is never compared directly (questions can be long).

1. Resolve `app_slug` → `app_id` via `GET /v1/app/by-slug/{slug}` (cached per client instance)
2. `GET /v1/app/{id}/datasets/hashes` → existing hashes
3. For each incoming question, compute `sha256(question.strip())`:
   - Hash **not found** → `POST /v1/app/{id}/datasets` (new question)
   - Hash found, `human_answer_hash` **differs** → `PATCH /v1/app/{id}/datasets/{dataset_id}` (updated answer)
   - Hash found, `human_answer_hash` **matches** → skip

### `run_evaluation(app_slug, app_version, callback, ...)`
1. Resolve `app_slug` → `app_id` via `GET /v1/app/by-slug/{slug}` (cached per client instance)
2. `GET /v1/app/{id}/datasets` → full question list
3. For each dataset item: `result = await callback(item["question"])` where
   `result` is an `AnswerWithCost(answer: str, cost: float | None)`
4. `POST /v1/app/{id}/evaluation` with:
   ```json
   {
     "app_version": "<app_version>",
     "evaluation_type": "<evaluation_type>",
     "app_answers": {
       "<dataset_id>": { "answer": "<answer>", "cost": 0.0123 },
       "<dataset_id>": { "answer": "<answer>", "cost": null }
     },
     "llm_judge_models": ["gpt-4o-mini"]
   }
   ```

---

## Auth

Uses **OAuth2 client credentials grant** against Zitadel.

Flow on first API call:
1. `GET {base_url}/.well-known` → get `issuer`
2. `POST {issuer}/oauth/v2/token` with `grant_type=client_credentials`, `client_id`, `client_secret`
3. Cache the token; refresh automatically when `expires_in` is reached

The `issuer` and token are cached on the client instance — no repeated discovery calls.

---

## Slug → ID caching

All three methods resolve `app_slug` → `app_id` via `GET /v1/app/by-slug/{slug}`. The resolved mapping is cached on the client instance so multiple method calls don't repeat the lookup.

---

## Slug format

- Lowercase, alphanumeric, hyphens only — e.g. `"my-app"`, `"gpt-wrapper-v2"`
- Enforced by the API (422 if invalid format)
- Chosen when the app is created in the admin UI; stable forever

---

## Dependencies

- `httpx` — HTTP client
- `pydantic` — response validation

---

## Usage example

```python
from eval_sdk import EvaluationClient

client = EvaluationClient(
    base_url="https://eval.mycompany.com",
    client_id="my-service@myproject.zitadel.cloud",
    client_secret="...",
)

# The app ("my-app") must already exist and this client must be bound to it
# (created in the admin UI). The SDK does not create apps.
client.add_questions("my-app", [
    {"question": "What is the capital of France?", "human_answer": "Paris"},
    {"question": "What is 2 + 2?", "human_answer": "4"},
])

# Run after each inference cycle
def my_llm(question: str) -> str:
    return my_model.complete(question)

client.run_evaluation(
    app_slug="my-app",
    app_version="v1.4.2",
    callback=my_llm,
    evaluation_type="LLM_ONLY",
    llm_judge_models=["gpt-4o-mini"],
)
```
