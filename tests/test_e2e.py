"""End-to-end test — requires a running server at http://localhost:8000."""

import pytest

from main import main


@pytest.mark.asyncio
async def test_full_evaluation_flow() -> None:
    await main()
