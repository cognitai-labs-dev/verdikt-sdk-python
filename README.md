# verdikt-sdk

Python SDK for [Verdikt](https://github.com/cognitai-labs-dev/verdikt) — a standalone AI evaluation service that decouples evaluation and LLM/human judging from the application being evaluated.

## Installation

```
pip install verdikt-sdk
```

## Usage

```python
from verdikt_sdk import EvaluationClient
from verdikt_sdk.models import EvaluationType, Question
from yalc import LLMModel

client = EvaluationClient(
    base_url="https://your-verdikt-instance.com",
    client_id="your-client-id",
    client_secret="your-client-secret",
)

# Register your app (idempotent — safe to call on every deploy)
await client.create_app(slug="my-app", name="My App")

# Sync questions to the dataset (idempotent)
await client.add_questions("my-app", [
    Question(question="What is the capital of France?", human_answer="Paris"),
])

# Run an evaluation cycle
await client.run_evaluation(
    app_slug="my-app",
    app_version="v1.2.0",
    callback=my_llm_function,  # async fn(question: str) -> str
    evaluation_type=EvaluationType.LLM_ONLY,
    llm_judge_models=[LLMModel.gpt_4o_mini],
)
```

`run_evaluation` calls your `callback` concurrently for every question in the dataset, then submits all answers to Verdikt for judgment.

## Authentication

The SDK authenticates via Zitadel OAuth2 client credentials. Create a machine user in your Zitadel project and pass its `client_id` and `client_secret` to `EvaluationClient`.
