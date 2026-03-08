"""
Example scenario: an LLM-powered geography assistant is evaluated after each deploy.

Run with:
    uv run main.py
"""

import asyncio
import logging

from yalc import LLMModel

from sdk.client import EvaluationClient
from sdk.models import EvaluationType, Question

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

QUESTIONS = [
    Question(question="What is the capital of France?", human_answer="Paris"),
    Question(question="What is the capital of Slovakia?", human_answer="Bratislava"),
]


async def my_llm(question: str) -> str:
    """Stub representing the application under evaluation."""
    answers = {
        "What is the capital of France?": "Paris",
        "What is the capital of Slovakia?": "Bratislava",
    }
    return answers.get(question, "I don't know")


async def main() -> None:
    client = EvaluationClient(
        base_url="http://localhost:8000",
        client_id="sdk-test",
        client_secret="test",
    )

    await client.create_app(slug="geo-assistant", name="Geography Assistant")

    await client.add_questions("geo-assistant", QUESTIONS)

    await client.run_evaluation(
        app_slug="geo-assistant",
        app_version="v1.0.0",
        callback=my_llm,
        evaluation_type=EvaluationType.LLM_ONLY,
        llm_judge_models=[LLMModel.gpt_4o_mini, LLMModel.gpt_5_mini],
    )


if __name__ == "__main__":
    asyncio.run(main())
