"""
JARVIS Backend — Gemini AI service layer.

Uses the official ``google-genai`` SDK Interactions API for stateful,
multi-turn conversations with Gemini 3.8 Flash.

Key design points
-----------------
- ``client.aio.interactions.create(stream=True)`` returns an AsyncStream of
  InteractionSSEEvent objects.
- Text chunks arrive as ``StepDelta`` events whose ``.delta`` field is a
  ``TextDelta`` (``delta.type == "text"``).
- The final ``InteractionCompletedEvent`` carries the interaction ID for
  multi-turn continuity — Google stores history server-side.
- ``client.aio.interactions.create()`` (stream=False) is kept as a
  non-streaming fallback for the existing POST /api/chat endpoint.
- Errors are classified into typed exceptions that FastAPI maps to
  appropriate HTTP status codes (503 / 504 / 429 / 502).
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator

from google import genai
from google.genai._gaos.types.interactions.stepdelta import StepDelta
from google.genai._gaos.types.interactions.textdelta import TextDelta
from google.genai._gaos.types.interactions.interactioncompletedevent import (
    InteractionCompletedEvent,
)
import httpx

from . import config

logger = logging.getLogger("jarvis.gemini")

# ── Module-level client ───────────────────────────────────────────
_client: genai.Client | None = None


def is_configured() -> bool:
    """Return True if the Gemini client has been initialised."""
    return _client is not None


def init_client() -> None:
    """Initialise the Gemini client (call once at app startup)."""
    global _client

    if not config.GEMINI_API_KEY:
        logger.warning(
            "GEMINI_API_KEY is not set. "
            "The /api/chat endpoint will return 503 until a key is configured."
        )
        _client = None
        return

    _client = genai.Client(api_key=config.GEMINI_API_KEY)
    logger.info("Gemini client initialised (model=%s)", config.GEMINI_MODEL)


def shutdown_client() -> None:
    """Tear down the Gemini client (call at app shutdown)."""
    global _client
    _client = None
    logger.info("Gemini client shut down")


# ── Error types ──────────────────────────────────────────────────

class GeminiUnavailableError(Exception):
    """Raised when the Gemini client is not configured."""


class GeminiTimeoutError(Exception):
    """Raised when a Gemini call exceeds the configured timeout."""


class GeminiUpstreamError(Exception):
    """Raised on any upstream Gemini API error."""


class GeminiRateLimitError(Exception):
    """Raised when the upstream API signals rate-limiting (429)."""


# ── Shared helpers ────────────────────────────────────────────────

def _build_kwargs(message: str, previous_interaction_id: str | None) -> dict:
    """Build keyword arguments for interactions.create()."""
    kwargs: dict = {
        "model": config.GEMINI_MODEL,
        "input": message,
        "system_instruction": config.JARVIS_SYSTEM_INSTRUCTION,
    }
    if previous_interaction_id:
        kwargs["previous_interaction_id"] = previous_interaction_id
    return kwargs


def _sdk_timeout() -> httpx.Timeout:
    """Return an httpx.Timeout sized to GEMINI_TIMEOUT_SECONDS."""
    return httpx.Timeout(
        connect=10.0,
        read=config.GEMINI_TIMEOUT_SECONDS,
        write=10.0,
        pool=5.0,
    )


def _classify_upstream_error(exc: Exception) -> None:
    """Re-raise *exc* as the appropriate typed service error."""
    if isinstance(exc, httpx.ReadTimeout):
        raise GeminiTimeoutError(
            f"Gemini did not respond within {config.GEMINI_TIMEOUT_SECONDS}s. "
            "Increase GEMINI_TIMEOUT_SECONDS in backend/.env."
        ) from exc
    msg = str(exc).lower()
    if "429" in msg or "rate" in msg or "resource_exhausted" in msg:
        raise GeminiRateLimitError(
            "Gemini API rate limit exceeded. Please try again in a moment."
        ) from exc
    if "404" in msg or "not_found" in msg or "not found" in msg:
        raise GeminiUpstreamError(
            f"Gemini model not found — check GEMINI_MODEL in backend/.env. "
            f"Detail: {exc}"
        ) from exc
    logger.exception("Gemini API error")
    raise GeminiUpstreamError(f"Gemini API error: {exc}") from exc


# ── Streaming chat ────────────────────────────────────────────────

async def chat_stream(
    message: str,
    previous_interaction_id: str | None = None,
) -> AsyncGenerator[tuple[str, str | None], None]:
    """Stream Gemini response chunks using the Interactions SSE API.

    Yields:
        ``("chunk", text)``      — for each incremental text delta
        ``("done", iid)``        — when the stream completes with interaction ID
        ``("error", message)``   — on a classified error (caller should surface)

    The caller is responsible for catching GeminiUnavailableError before
    iterating; other errors are yielded as ``("error", ...)`` events so the
    SSE stream can close gracefully without dropping the HTTP connection.
    """
    if _client is None:
        raise GeminiUnavailableError(
            "Gemini API key is not configured. "
            "Set GEMINI_API_KEY in backend/.env and restart the server."
        )

    kwargs = _build_kwargs(message, previous_interaction_id)
    t0 = time.monotonic()
    first_chunk_logged = False
    chunk_count = 0
    event_count = 0

    logger.info(
        "Stream request — model=%s, prev_id=%s",
        config.GEMINI_MODEL,
        previous_interaction_id or "none",
    )

    try:
        logger.debug("Calling aio.interactions.create(stream=True) ...")
        stream = await _client.aio.interactions.create(
            **kwargs,
            stream=True,
            timeout=_sdk_timeout(),
        )
        logger.info("Stream established in %.2fs — iterating events ...", time.monotonic() - t0)

        async for event in stream:
            event_count += 1
            event_type = getattr(event, "event_type", type(event).__name__)
            logger.debug("SSE event #%d: type=%s", event_count, event_type)

            if isinstance(event, StepDelta):
                delta = event.delta
                logger.debug(
                    "  StepDelta index=%s delta_type=%s",
                    event.index,
                    type(delta).__name__,
                )
                if isinstance(delta, TextDelta) and delta.text:
                    chunk_count += 1
                    if not first_chunk_logged:
                        logger.info(
                            "First text chunk in %.2fs", time.monotonic() - t0
                        )
                        first_chunk_logged = True
                    yield ("chunk", delta.text)

            elif isinstance(event, InteractionCompletedEvent):
                elapsed = time.monotonic() - t0
                iid = event.interaction.id if event.interaction else None
                logger.info(
                    "Stream complete — %.2fs total, %d events, %d text chunks, "
                    "interaction_id=%s",
                    elapsed,
                    event_count,
                    chunk_count,
                    iid,
                )
                yield ("done", iid)
                return  # stream is finished

            else:
                logger.debug("  Skipping event type=%s", event_type)

        # Stream exhausted without InteractionCompletedEvent
        if chunk_count == 0:
            logger.warning(
                "Stream ended after %.2fs with NO text chunks and NO completed event "
                "(%d events total). Possible model safety filter or empty response.",
                time.monotonic() - t0,
                event_count,
            )
            yield ("error", "No response received from Gemini. The request may have been filtered.")
        else:
            logger.warning(
                "Stream ended after %d text chunks but without an interaction.completed event.",
                chunk_count,
            )
            yield ("done", None)

    except httpx.ReadTimeout as exc:
        err_msg = (
            f"Gemini stream timed out after {config.GEMINI_TIMEOUT_SECONDS}s. "
            "Increase GEMINI_TIMEOUT_SECONDS in backend/.env."
        )
        logger.warning("Stream timeout: %s", err_msg)
        yield ("error", err_msg)
    except Exception as exc:
        logger.exception("Unexpected error during Gemini stream (after %.2fs)", time.monotonic() - t0)
        try:
            _classify_upstream_error(exc)
        except (GeminiTimeoutError, GeminiRateLimitError, GeminiUpstreamError) as typed:
            yield ("error", str(typed))
        except Exception as e2:
            yield ("error", f"Gemini error: {e2}")


# ── Non-streaming fallback ────────────────────────────────────────

async def chat(
    message: str,
    previous_interaction_id: str | None = None,
) -> tuple[str, str]:
    """Send *message* to Gemini and return ``(reply_text, interaction_id)``.

    Non-streaming — keeps the existing ``POST /api/chat`` endpoint working.

    Raises
    ------
    GeminiUnavailableError / GeminiTimeoutError / GeminiRateLimitError /
    GeminiUpstreamError — same classification as the streaming path.
    """
    if _client is None:
        raise GeminiUnavailableError(
            "Gemini API key is not configured. "
            "Set GEMINI_API_KEY in backend/.env and restart the server."
        )

    kwargs = _build_kwargs(message, previous_interaction_id)
    t0 = time.monotonic()

    logger.info(
        "Non-stream request — model=%s, prev_id=%s",
        config.GEMINI_MODEL,
        previous_interaction_id or "none",
    )

    try:
        interaction = await _client.aio.interactions.create(
            **kwargs,
            timeout=_sdk_timeout(),
        )
    except Exception as exc:
        _classify_upstream_error(exc)
        raise  # unreachable

    elapsed = time.monotonic() - t0
    logger.info("Non-stream response: %.2fs, interaction_id=%s", elapsed, interaction.id)

    reply_text: str = (
        interaction.output_text
        if interaction.output_text
        else "I'm sorry, I couldn't generate a response."
    )
    return reply_text, interaction.id
