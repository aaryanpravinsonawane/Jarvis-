"""
JARVIS Backend — Configuration.

All settings are loaded from environment variables (via .env).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

# Load .env from the backend/ directory (one level up from app/).
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

# ── Required ──────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

# ── Model / Persona ──────────────────────────────────────────────
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

JARVIS_SYSTEM_INSTRUCTION: str = os.getenv(
    "JARVIS_SYSTEM_INSTRUCTION",
    (
        "You are JARVIS, a highly advanced AI assistant inspired by the AI "
        "from Iron Man. You are polite, witty, efficient, and address the "
        'user as "Sir" or "Ma\'am". Keep responses concise but helpful. '
        "You have a dry sense of humour and a calm, confident demeanour."
    ),
)

# ── Server ────────────────────────────────────────────────────────
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8000"))

# ── Limits ────────────────────────────────────────────────────────
# Maximum conversation turns retained server-side per interaction chain.
MAX_HISTORY_TURNS: int = int(os.getenv("MAX_HISTORY_TURNS", "20"))

# Timeout in seconds for a single Gemini API call.
# Interactions API first-token latency can be 30-60 s; default 90 s gives headroom.
GEMINI_TIMEOUT_SECONDS: float = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "90"))

# CORS origins allowed during development.
CORS_ORIGINS: list[str] = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]
