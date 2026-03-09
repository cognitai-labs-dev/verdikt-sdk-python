"""HTTP utilities for the Evaluation SDK."""

from __future__ import annotations

import httpx


def raise_for_status(resp: httpx.Response) -> None:
    """Like ``resp.raise_for_status()`` but includes the response body in the error."""
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise httpx.HTTPStatusError(
            f"{exc.response.status_code} {exc.response.reason_phrase} "
            f"for url '{exc.request.url}' — body: {exc.response.text}",
            request=exc.request,
            response=exc.response,
        ) from exc
