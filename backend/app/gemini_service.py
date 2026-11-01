"""
JARVIS Backend — Gemini AI service layer.

Uses the official ``google-genai`` SDK Interactions API for stateful,
multi-turn conversations with Gemini 3.8 Flash.

Key design points
-----------------
- ``client.aio.interactions.create(background=True)`` returns a stored
  interaction ID before generation completes.
- Text chunks arrive as ``StepDelta`` events whose ``.delta`` field is a
  ``TextDelta`` (``delta.type == "text"``).
- The final ``InteractionCompletedEvent`` carries the interaction ID for
  multi-turn continuity — Google stores history server-side.
- ``client.aio.interactions.get(id=..., stream=True)`` yields text deltas and
  terminal events; status reads provide a polling fallback.
- Errors are classified into typed exceptions that FastAPI maps to
  appropriate HTTP status codes (503 / 504 / 429 / 502).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import AsyncGenerator

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
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

    # The SDK retries transient errors by default. Keep each interaction to one
    # attempt so a retry cannot silently stretch a request beyond our deadline.
    _client = genai.Client(
        api_key=config.GEMINI_API_KEY,
        http_options=genai_types.HttpOptions(
            retry_options=genai_types.HttpRetryOptions(attempts=1),
        ),
    )
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
        "generation_config": dict(config.GEMINI_GENERATION_CONFIG),
    }
    if previous_interaction_id is not None:
        kwargs["previous_interaction_id"] = previous_interaction_id
    return kwargs


def _sdk_timeout() -> float:
    """Return a whole-call deadline for Interactions, including continuation hops."""
    return config.GEMINI_TIMEOUT_SECONDS


def _is_timeout_error(exc: BaseException) -> bool:
    """Recognize timeouts wrapped by SDK continuation errors."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (httpx.TimeoutException, TimeoutError)):
            return True
        current = current.__cause__ or current.__context__
    return False


def _log_upstream_failure(
    operation: str,
    started_at: float,
    previous_interaction_id: str | None,
    exc: BaseException,
) -> None:
    status = exc.code if isinstance(exc, genai_errors.APIError) else None
    if _is_timeout_error(exc):
        classification = "timeout"
    elif status == 429:
        classification = "rate_limit"
    elif status == 404:
        classification = "not_found"
    else:
        classification = "upstream_error"

    logger.warning(
        "gemini_request_failed operation=%s elapsed_ms=%d "
        "has_previous_interaction_id=%s classification=%s exception_type=%s "
        "upstream_status=%s",
        operation,
        round((time.perf_counter() - started_at) * 1000),
        bool(previous_interaction_id),
        classification,
        type(exc).__name__,
        status,
    )


async def _close_stream(stream: object, iterator: object) -> None:
    """Close an async stream without replacing the request's original error."""
    closed: set[int] = set()
    for resource in (iterator, stream):
        if id(resource) in closed:
            continue
        closed.add(id(resource))
        close = getattr(resource, "aclose", None)
        if not callable(close):
            continue
        try:
            result = close()
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.debug(
                "gemini_stream_close_failed resource_type=%s",
                type(resource).__name__,
            )


def _classify_upstream_error(exc: Exception) -> None:
    """Re-raise *exc* as the appropriate typed service error."""
    if _is_timeout_error(exc):
        raise GeminiTimeoutError(
            f"Gemini did not respond within {config.GEMINI_TIMEOUT_SECONDS}s. "
            "The configured Gemini request deadline was reached."
        ) from exc
    if isinstance(exc, genai_errors.APIError) and exc.code == 429:
        raise GeminiRateLimitError(
            "Gemini API rate limit exceeded. Please try again in a moment."
        ) from exc
    if isinstance(exc, genai_errors.APIError) and exc.code == 404:
        raise GeminiUpstreamError(
            "Gemini model or interaction was not found (HTTP 404)."
        ) from exc
    status = exc.code if isinstance(exc, genai_errors.APIError) else None
    if status is not None:
        raise GeminiUpstreamError(f"Gemini API returned HTTP {status}.") from exc
    raise GeminiUpstreamError(
        "Gemini request failed due to an upstream or transport error."
    ) from exc


def _status_value(interaction: object) -> str:
    status = getattr(interaction, "status", "unknown")
    return str(getattr(status, "value", status))


def classify_interaction_status(interaction: object) -> str:
    """Return pending, completed, or error for SDK interaction states."""
    status = _status_value(interaction)
    if status in {"queued", "in_progress", "requires_continuation"}:
        return "pending"
    if status == "completed":
        return "completed"
    return "error"


def interaction_error_message(interaction: object) -> str:
    """Return a safe status description without forwarding SDK error details."""
    status = _status_value(interaction)
    messages = {
        "failed": "Gemini interaction failed.",
        "cancelled": "Gemini interaction was cancelled.",
        "incomplete": "Gemini interaction ended before a complete response was available.",
        "budget_exceeded": "Gemini interaction exceeded its execution budget.",
        "requires_action": "Gemini interaction requires an action that this client cannot provide.",
    }
    if status in messages:
        return messages[status]
    return "Gemini interaction ended in an unsupported state."


async def start_background_interaction(
    message: str,
    previous_interaction_id: str | None = None,
):
    """Start a server-stored Gemini interaction and return as soon as it is accepted."""
    if _client is None:
        raise GeminiUnavailableError("Gemini API is not configured.")

    if previous_interaction_id is not None:
        previous = await get_background_interaction(previous_interaction_id)
        if _status_value(previous) != "completed":
            raise GeminiUpstreamError(
                "The previous Gemini interaction must be completed before continuing."
            )

    kwargs = _build_kwargs(message, previous_interaction_id)
    started_at = time.monotonic()
    logger.info(
        "gemini_background_start operation=create has_previous_interaction_id=%s",
        previous_interaction_id is not None,
    )
    try:
        interaction = await asyncio.wait_for(
            _client.aio.interactions.create(
                **kwargs,
                background=True,
                store=True,
                timeout=_sdk_timeout(),
            ),
            timeout=config.GEMINI_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        _log_upstream_failure("background_create", started_at, previous_interaction_id, exc)
        _classify_upstream_error(exc)
        raise

    if not getattr(interaction, "id", None):
        raise GeminiUpstreamError("Gemini accepted the request without returning an interaction ID.")
    logger.info(
        "gemini_background_accepted elapsed_ms=%d status=%s",
        round((time.monotonic() - started_at) * 1000),
        _status_value(interaction),
    )
    return interaction


async def get_background_interaction(interaction_id: str):
    """Retrieve a server-stored background interaction by its actual ID."""
    if _client is None:
        raise GeminiUnavailableError("Gemini API is not configured.")

    started_at = time.monotonic()
    try:
        return await asyncio.wait_for(
            _client.aio.interactions.get(
                id=interaction_id,
                timeout=_sdk_timeout(),
            ),
            timeout=config.GEMINI_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        _log_upstream_failure("background_get", started_at, None, exc)
        _classify_upstream_error(exc)
        raise


async def cancel_background_interaction(interaction_id: str):
    """Ask Gemini to cancel a running background interaction."""
    if _client is None:
        raise GeminiUnavailableError("Gemini API is not configured.")
    started_at = time.monotonic()
    try:
        return await asyncio.wait_for(
            _client.aio.interactions.cancel(
                id=interaction_id,
                timeout=_sdk_timeout(),
            ),
            timeout=config.GEMINI_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        _log_upstream_failure("background_cancel", started_at, None, exc)
        _classify_upstream_error(exc)
        raise


async def stream_background_interaction(
    interaction_id: str,
    last_event_id: str | None = None,
) -> AsyncGenerator[tuple[str, str | None], None]:
    """Stream a background interaction using the SDK's async get(stream=True)."""
    if _client is None:
        raise GeminiUnavailableError("Gemini API is not configured.")

    started_at = time.monotonic()
    stream = None
    iterator = None
    pending_event: asyncio.Task | None = None
    chunk_count = 0
    streamed_text = ""
    poll_after_disconnect = False
    terminal_id = interaction_id

    try:
        stream = await asyncio.wait_for(
            _client.aio.interactions.get(
                id=interaction_id,
                stream=True,
                last_event_id=last_event_id,
                timeout=_sdk_timeout(),
            ),
            timeout=config.GEMINI_TIMEOUT_SECONDS,
        )
        if not hasattr(stream, "__aiter__"):
            classification = classify_interaction_status(stream)
            if classification == "completed":
                terminal_id = getattr(stream, "id", None) or interaction_id
                final_text = getattr(stream, "output_text", None) or ""
                yield ("replace", final_text)
                yield ("done", terminal_id)
                return
            if classification == "error":
                yield ("error", interaction_error_message(stream))
                return
            poll_after_disconnect = True
        else:
            iterator = stream.__aiter__()

        while iterator is not None:
            pending_event = asyncio.create_task(iterator.__anext__())
            event_started = time.monotonic()
            while not pending_event.done():
                wait_slice = min(15.0, config.GEMINI_TIMEOUT_SECONDS)
                done, _ = await asyncio.wait({pending_event}, timeout=wait_slice)
                if done:
                    break
                if time.monotonic() - event_started >= config.GEMINI_TIMEOUT_SECONDS:
                    pending_event.cancel()
                    await asyncio.gather(pending_event, return_exceptions=True)
                    poll_after_disconnect = True
                    break
                yield ("heartbeat", None)

            if poll_after_disconnect:
                break
            try:
                event = pending_event.result()
            except StopAsyncIteration:
                poll_after_disconnect = True
                break
            except (httpx.TimeoutException, TimeoutError):
                poll_after_disconnect = True
                break
            finally:
                pending_event = None

            if isinstance(event, StepDelta):
                delta = event.delta
                event_id = getattr(event, "event_id", None)
                if event_id:
                    last_event_id = event_id
                if isinstance(delta, TextDelta) and delta.text:
                    chunk_count += 1
                    streamed_text += delta.text
                    yield ("chunk", delta.text)
            elif isinstance(event, InteractionCompletedEvent):
                interaction = event.interaction
                classification = (
                    classify_interaction_status(interaction)
                    if interaction
                    else "error"
                )
                if classification == "pending":
                    continue
                if classification == "completed":
                    terminal_id = getattr(interaction, "id", None) or interaction_id
                    final = await get_background_interaction(terminal_id)
                    if classify_interaction_status(final) != "completed":
                        yield ("error", interaction_error_message(final))
                        return
                    final_text = getattr(final, "output_text", None) or ""
                    if final_text != streamed_text:
                        yield ("replace", final_text)
                    logger.info(
                        "gemini_background_stream_completed elapsed_ms=%d chunk_count=%d",
                        round((time.monotonic() - started_at) * 1000),
                        chunk_count,
                    )
                    yield ("done", getattr(final, "id", None) or terminal_id)
                    return
                yield ("error", interaction_error_message(interaction))
                return
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _log_upstream_failure("background_stream", started_at, None, exc)
        if _is_timeout_error(exc) or isinstance(exc, (httpx.TransportError, ConnectionError)):
            poll_after_disconnect = True
        else:
            try:
                _classify_upstream_error(exc)
            except (GeminiTimeoutError, GeminiRateLimitError, GeminiUpstreamError) as typed:
                yield ("error", str(typed))
                return
            except Exception:
                yield ("error", "Gemini stream failed.")
                return
    finally:
        if pending_event is not None and not pending_event.done():
            pending_event.cancel()
            await asyncio.gather(pending_event, return_exceptions=True)
        if stream is not None:
            await _close_stream(stream, iterator if iterator is not None else stream)

    if poll_after_disconnect:
        try:
            final = await wait_for_background_interaction(interaction_id)
        except (GeminiTimeoutError, GeminiRateLimitError, GeminiUpstreamError) as typed:
            yield ("error", str(typed))
            return
        except Exception as exc:
            try:
                _classify_upstream_error(exc)
            except (GeminiTimeoutError, GeminiRateLimitError, GeminiUpstreamError) as typed:
                yield ("error", str(typed))
            return
        final_id = getattr(final, "id", None) or interaction_id
        final_text = getattr(final, "output_text", None) or ""
        if final_text != streamed_text:
            yield ("replace", final_text)
        logger.info(
            "gemini_background_poll_completed elapsed_ms=%d chunk_count=%d",
            round((time.monotonic() - started_at) * 1000),
            chunk_count,
        )
        yield ("done", final_id)


async def wait_for_background_interaction(
    interaction_id: str,
):
    """Poll a background interaction for the legacy synchronous chat endpoint."""
    while True:
        interaction = await get_background_interaction(interaction_id)
        classification = classify_interaction_status(interaction)
        if classification == "completed":
            return interaction
        if classification == "error":
            raise GeminiUpstreamError(interaction_error_message(interaction))
        await asyncio.sleep(max(config.GEMINI_POLL_INTERVAL_SECONDS, 0.1))


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
    try:
        interaction = await start_background_interaction(
            message,
            previous_interaction_id,
        )
        async for event in stream_background_interaction(interaction.id):
            yield event
    except (GeminiUnavailableError, GeminiTimeoutError, GeminiRateLimitError, GeminiUpstreamError) as exc:
        yield ("error", str(exc))


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
    interaction = await start_background_interaction(
        message,
        previous_interaction_id,
    )
    completed = await wait_for_background_interaction(interaction.id)
    reply_text = (
        completed.output_text
        if completed.output_text
        else "I'm sorry, I couldn't generate a response."
    )
    return reply_text, completed.id or interaction.id
