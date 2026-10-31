"""
JARVIS Backend — Compatibility entrypoint.

The actual application lives in the ``app`` package.  This file
re-exports ``app`` so that ``uvicorn main:app --reload`` continues
to work from the ``backend/`` directory.

Preferred invocation:
  uvicorn app.main:app --reload
"""

from app.main import app  # noqa: F401
