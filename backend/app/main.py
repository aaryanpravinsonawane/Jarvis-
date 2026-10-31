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
import logging
import logging.config
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


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest, request: Request) -> StreamingResponse:
    """Stream JARVIS response as Server-Sent Events (SSE).

    SSE event types sent to the client:
      data: {"type":"chunk","text":"..."}         — incremental text
      data: {"type":"done","interaction_id":"..."}— stream complete
      data: {"type":"error","message":"..."}      — error occurred
    """
    logger.info(
        "POST /api/chat/stream — message_len=%d prev_id=%s",
        len(req.message),
        req.previous_interaction_id or "none",
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
        logger.debug("SSE event_generator started")
        try:
            async for kind, value in gemini_service.chat_stream(
                message=req.message,
                previous_interaction_id=req.previous_interaction_id,
            ):
                if kind == "chunk":
                    payload = json.dumps({"type": "chunk", "text": value})
                elif kind == "done":
                    payload = json.dumps({"type": "done", "interaction_id": value})
                elif kind == "error":
                    payload = json.dumps({"type": "error", "message": value})
                else:
                    logger.warning("Unknown SSE kind: %r", kind)
                    continue

                logger.debug("SSE yield: %s", payload[:80])
                yield f"data: {payload}\n\n"

        except gemini_service.GeminiUnavailableError as exc:
            logger.error("Gemini unavailable in stream: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        except Exception as exc:
            logger.exception("Unexpected error in SSE event_generator")
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

        logger.debug("SSE event_generator finished")

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
    logger.info(
        "POST /api/chat — message_len=%d prev_id=%s",
        len(req.message),
        req.previous_interaction_id or "none",
    )
    try:
        reply_text, interaction_id = await gemini_service.chat(
            message=req.message,
            previous_interaction_id=req.previous_interaction_id,
        )
    except gemini_service.GeminiUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except gemini_service.GeminiTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except gemini_service.GeminiRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except gemini_service.GeminiUpstreamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return ChatResponse(
        reply=reply_text,
        interaction_id=interaction_id,
        model=GEMINI_MODEL,
    )


# ── Entrypoint ────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True, log_level="debug")
