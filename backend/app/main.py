"""
JARVIS Backend — FastAPI server with Gemini AI integration.

Endpoints:
  GET  /api/health      — Health check (verifies Gemini client is configured)
  POST /api/chat        — Non-streaming: send a message, receive full response
  POST /api/chat/stream — Streaming SSE: receive incremental text deltas

Run (from the backend/ directory):
  pip install -r requirements.txt
  cp .env.example .env   # fill in GEMINI_API_KEY
  uvicorn app.main:app --reload --log-level debug
"""

from __future__ import annotations

import json
import asyncio
import logging
import logging.config
import time
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .config import CORS_ORIGINS, GEMINI_MODEL, HOST, PORT
from .schemas import ChatRequest, ChatResponse, HealthResponse
from . import gemini_service

# ── Logging setup ─────────────────────────────────────────────────
# Ensure DEBUG messages from jarvis.gemini are always visible on the console.
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("jarvis")

# Keep third-party loggers quieter so our output is readable.
for _noisy in ("httpx", "httpcore", "google", "uvicorn.access"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


# ── Lifespan ──────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialise and tear down the Gemini client."""
    gemini_service.init_client()
    yield
    gemini_service.shutdown_client()


# ── FastAPI app ───────────────────────────────────────────────────
app = FastAPI(
    title="JARVIS API",
    version="0.4.0",
    lifespan=lifespan,
)

# CORS — scoped to the Vite dev server origin by default.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Endpoints ─────────────────────────────────────────────────────

@app.get("/api/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check — reports whether the Gemini client is ready."""
    return HealthResponse(
        status="ok",
        gemini_configured=gemini_service.is_configured(),
        model=GEMINI_MODEL,
    )


def _interaction_http_exception(exc: Exception) -> HTTPException:
    if isinstance(exc, gemini_service.GeminiUnavailableError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, gemini_service.GeminiTimeoutError):
        return HTTPException(status_code=504, detail=str(exc))
    if isinstance(exc, gemini_service.GeminiRateLimitError):
        return HTTPException(status_code=429, detail=str(exc))
    if isinstance(exc, gemini_service.GeminiUpstreamError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=502, detail="Gemini request failed.")


async def _stream_with_heartbeats(events, interval_seconds: float = 15.0):
    """Keep client SSE connections active while background work is quiet."""
    iterator = events.__aiter__()
    pending: asyncio.Task | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.create_task(iterator.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=interval_seconds)
            if not done:
                yield ("heartbeat", None)
                continue
            try:
                event = pending.result()
            except StopAsyncIteration:
                return
            pending = None
            yield event
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        close = getattr(iterator, "aclose", None)
        if callable(close):
            await close()


@app.post("/api/interactions", status_code=202)
async def start_interaction(req: ChatRequest) -> dict[str, str]:
    """Start a stored background interaction and return its ID immediately."""
    logger.info(
        "request_received endpoint=/api/interactions "
        "has_previous_interaction_id=%s",
        req.previous_interaction_id is not None,
    )
    try:
        interaction = await gemini_service.start_background_interaction(
            req.message,
            req.previous_interaction_id,
        )
    except Exception as exc:
        raise _interaction_http_exception(exc) from exc
    return {
        "interaction_id": interaction.id,
        "status": str(getattr(interaction.status, "value", interaction.status)),
        "model": GEMINI_MODEL,
    }


@app.get("/api/interactions/{interaction_id}")
async def interaction_status(interaction_id: str) -> dict[str, str]:
    """Retrieve background status, exposing output only after completion."""
    try:
        interaction = await gemini_service.get_background_interaction(interaction_id)
    except Exception as exc:
        raise _interaction_http_exception(exc) from exc

    status = str(getattr(interaction.status, "value", interaction.status))
    result = {
        "interaction_id": interaction.id or interaction_id,
        "status": status,
        "model": GEMINI_MODEL,
    }
    classification = gemini_service.classify_interaction_status(interaction)
    if classification == "completed":
        result["reply"] = interaction.output_text or ""
    elif classification == "error":
        result["error"] = gemini_service.interaction_error_message(interaction)
    return result


@app.get("/api/interactions/{interaction_id}/stream")
async def stream_interaction(interaction_id: str, last_event_id: str | None = None):
    """Stream a stored background interaction, including resumable SDK events."""
    if not gemini_service.is_configured():
        raise HTTPException(status_code=503, detail="Gemini API is not configured.")

    async def event_generator() -> AsyncGenerator[str, None]:
        outcome = "completed"
        try:
            events = gemini_service.stream_background_interaction(
                interaction_id, last_event_id
            )
            async for kind, value in _stream_with_heartbeats(events):
                if kind == "heartbeat":
                    yield ": keep-alive\n\n"
                    continue
                if kind == "chunk":
                    payload = {"type": "chunk", "text": value}
                elif kind == "replace":
                    payload = {"type": "replace", "text": value}
                elif kind == "done":
                    payload = {"type": "done", "interaction_id": value}
                else:
                    outcome = "error"
                    payload = {"type": "error", "message": value}
                yield f"data: {json.dumps(payload)}\n\n"
        except asyncio.CancelledError:
            outcome = "client_cancelled"
            raise
        except Exception as exc:
            outcome = "internal_error"
            logger.error(
                "request_failed endpoint=/api/interactions/stream "
                "exception_type=%s",
                type(exc).__name__,
            )
            yield "data: {\"type\":\"error\",\"message\":\"Gemini stream failed.\"}\n\n"
        finally:
            logger.info(
                "request_completed endpoint=/api/interactions/stream outcome=%s",
                outcome,
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/interactions/{interaction_id}/cancel")
async def cancel_interaction(interaction_id: str) -> dict[str, str]:
    """Cancel an accepted background interaction."""
    try:
        interaction = await gemini_service.cancel_background_interaction(interaction_id)
    except Exception as exc:
        raise _interaction_http_exception(exc) from exc
    return {
        "interaction_id": interaction.id or interaction_id,
        "status": str(getattr(interaction.status, "value", interaction.status)),
    }


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest, request: Request) -> StreamingResponse:
    """Stream JARVIS response as Server-Sent Events (SSE).

    SSE event types sent to the client:
      data: {"type":"chunk","text":"..."}         — incremental text
      data: {"type":"done","interaction_id":"..."}— stream complete
      data: {"type":"error","message":"..."}      — error occurred
    """
    request_started = time.perf_counter()
    logger.info(
        "request_received endpoint=/api/chat/stream "
        "has_previous_interaction_id=%s",
        bool(req.previous_interaction_id),
    )

    # Raise immediately if client not configured — before opening the stream.
    if not gemini_service.is_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Gemini API key is not configured. "
                "Set GEMINI_API_KEY in backend/.env and restart the server."
            ),
        )

    async def event_generator() -> AsyncGenerator[str, None]:
        outcome = "completed"
        logger.debug("SSE event_generator started")
        try:
            events = gemini_service.chat_stream(
                message=req.message,
                previous_interaction_id=req.previous_interaction_id,
            )
            async for kind, value in _stream_with_heartbeats(events):
                if kind == "heartbeat":
                    yield ": keep-alive\n\n"
                    continue
                if kind == "chunk":
                    payload = json.dumps({"type": "chunk", "text": value})
                elif kind == "replace":
                    payload = json.dumps({"type": "replace", "text": value})
                elif kind == "done":
                    payload = json.dumps({"type": "done", "interaction_id": value})
                elif kind == "error":
                    payload = json.dumps({"type": "error", "message": value})
                    outcome = "upstream_error"
                else:
                    logger.warning("Unknown SSE kind: %r", kind)
                    continue

                logger.debug("sse_event_sent type=%s", kind)
                yield f"data: {payload}\n\n"

        except gemini_service.GeminiUnavailableError as exc:
            outcome = "unavailable"
            logger.error("request_failed endpoint=/api/chat/stream classification=unavailable")
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        except Exception as exc:
            outcome = "internal_error"
            logger.error(
                "request_failed endpoint=/api/chat/stream exception_type=%s",
                type(exc).__name__,
            )
            yield f"data: {json.dumps({'type': 'error', 'message': 'The JARVIS backend encountered an internal error.'})}\n\n"
        finally:
            logger.info(
                "request_completed endpoint=/api/chat/stream duration_ms=%d outcome=%s",
                round((time.perf_counter() - request_started) * 1000),
                outcome,
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",     # disable nginx/proxy buffering
            "Connection": "keep-alive",
        },
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """Send user message to Gemini and return the full JARVIS response."""
    request_started = time.perf_counter()
    logger.info(
        "request_received endpoint=/api/chat has_previous_interaction_id=%s",
        bool(req.previous_interaction_id),
    )
    try:
        reply_text, interaction_id = await gemini_service.chat(
            message=req.message,
            previous_interaction_id=req.previous_interaction_id,
        )
    except gemini_service.GeminiUnavailableError as exc:
        logger.warning("request_failed endpoint=/api/chat classification=unavailable")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except gemini_service.GeminiTimeoutError as exc:
        logger.warning("request_failed endpoint=/api/chat classification=timeout")
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except gemini_service.GeminiRateLimitError as exc:
        logger.warning("request_failed endpoint=/api/chat classification=rate_limit")
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except gemini_service.GeminiUpstreamError as exc:
        logger.warning(
            "request_failed endpoint=/api/chat classification=upstream_error"
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    logger.info(
        "request_completed endpoint=/api/chat duration_ms=%d outcome=completed",
        round((time.perf_counter() - request_started) * 1000),
    )
    return ChatResponse(
        reply=reply_text,
        interaction_id=interaction_id,
        model=GEMINI_MODEL,
    )


# ── Entrypoint ────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True, log_level="debug")
