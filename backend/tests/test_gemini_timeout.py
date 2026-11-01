"""Deterministic timeout coverage for the Gemini service.

These tests replace the SDK client with local async fakes.  They never load
the backend .env file and never make a network request.
"""

from __future__ import annotations

import asyncio
import json
import types
import unittest

import dotenv

# Prevent config import from reading backend/.env in this test module.
dotenv.load_dotenv = lambda *args, **kwargs: None

from fastapi import HTTPException

from app import gemini_service, main
from app.schemas import ChatRequest


class FakeTextDelta:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeStepDelta:
    def __init__(self, text: str, index: int = 0) -> None:
        self.delta = FakeTextDelta(text)
        self.index = index
        self.event_type = "step.delta"


class FakeInteractionCompletedEvent:
    def __init__(self, interaction_id: str, status: str = "completed") -> None:
        self.interaction = types.SimpleNamespace(id=interaction_id, status=status)
        self.event_type = "interaction.completed"


class FakeStream:
    """Async stream that optionally hangs after its supplied events."""

    def __init__(self, events: list[object], *, hang_after_events: bool = False) -> None:
        self._events = iter(events)
        self._hang_after_events = hang_after_events
        self.cancelled = False
        self.closed = False
        self._never = asyncio.Event()

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._events)
        except StopIteration:
            if not self._hang_after_events:
                raise StopAsyncIteration
            try:
                await self._never.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
            raise AssertionError("A hanging stream unexpectedly completed")

    async def aclose(self) -> None:
        self.closed = True


class FakeInteractions:
    def __init__(self, handler) -> None:
        self.handler = handler
        self.get_handler = None
        self.status_handler = None
        self.calls: list[dict] = []
        self.get_calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return await self.handler(kwargs)

    async def get(self, **kwargs):
        self.get_calls.append(kwargs)
        handler = self.get_handler if kwargs.get("stream") else self.status_handler
        handler = handler or self.get_handler
        if handler is None:
            raise AssertionError("A mocked background stream was not configured")
        return await handler(kwargs)


class FakeClient:
    def __init__(self, handler) -> None:
        self.interactions = FakeInteractions(handler)
        self.aio = types.SimpleNamespace(interactions=self.interactions)


async def _return(value):
    return value


class GeminiTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_client = gemini_service._client
        self.original_timeout = gemini_service.config.GEMINI_TIMEOUT_SECONDS
        self.original_step_delta = gemini_service.StepDelta
        self.original_text_delta = gemini_service.TextDelta
        self.original_completed_event = gemini_service.InteractionCompletedEvent
        gemini_service.config.GEMINI_TIMEOUT_SECONDS = 0.05
        gemini_service.StepDelta = FakeStepDelta
        gemini_service.TextDelta = FakeTextDelta
        gemini_service.InteractionCompletedEvent = FakeInteractionCompletedEvent

    async def asyncTearDown(self) -> None:
        gemini_service._client = self.original_client
        gemini_service.config.GEMINI_TIMEOUT_SECONDS = self.original_timeout
        gemini_service.StepDelta = self.original_step_delta
        gemini_service.TextDelta = self.original_text_delta
        gemini_service.InteractionCompletedEvent = self.original_completed_event

    def set_client(self, handler) -> FakeClient:
        client = FakeClient(handler)
        gemini_service._client = client
        return client

    async def test_non_streaming_hang_uses_absolute_deadline(self) -> None:
        async def never_returns(_kwargs):
            await asyncio.Event().wait()

        client = self.set_client(never_returns)

        with self.assertRaises(gemini_service.GeminiTimeoutError):
            await gemini_service.chat("test message")

        self.assertEqual(client.interactions.calls[0]["timeout"], 0.05)

    async def test_stream_hang_before_first_event_yields_safe_error_and_closes(self) -> None:
        stream = FakeStream([], hang_after_events=True)

        async def accept_interaction(_kwargs):
            return types.SimpleNamespace(id="accepted-id", status="in_progress")

        client = self.set_client(accept_interaction)
        client.aio.interactions.get_handler = lambda _kwargs: _return(stream)
        client.aio.interactions.status_handler = lambda _kwargs: _return(
            types.SimpleNamespace(id="accepted-id", status="failed", output_text="")
        )
        received = [
            item
            async for item in gemini_service.chat_stream("test message")
            if item[0] != "heartbeat"
        ]

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0][0], "error")
        self.assertIn("failed", received[0][1].lower())
        self.assertTrue(stream.cancelled)
        self.assertTrue(stream.closed)

    async def test_stream_hang_after_chunk_uses_original_deadline_and_closes(self) -> None:
        stream = FakeStream([FakeStepDelta("first")], hang_after_events=True)

        async def accept_interaction(_kwargs):
            return types.SimpleNamespace(id="accepted-id", status="in_progress")

        client = self.set_client(accept_interaction)
        client.aio.interactions.get_handler = lambda _kwargs: _return(stream)
        client.aio.interactions.status_handler = lambda _kwargs: _return(
            types.SimpleNamespace(id="accepted-id", status="failed", output_text="")
        )
        received = [
            item
            async for item in gemini_service.chat_stream("test message")
            if item[0] != "heartbeat"
        ]

        self.assertEqual(received[0], ("chunk", "first"))
        self.assertEqual(received[1][0], "error")
        self.assertTrue(stream.cancelled)
        self.assertTrue(stream.closed)

    async def test_background_stream_timeout_bounds_idle_wait_after_delayed_chunk(self) -> None:
        class DelayedThenHangingStream(FakeStream):
            def __init__(self) -> None:
                super().__init__([], hang_after_events=True)
                self.first_event = True

            async def __anext__(self):
                if self.first_event:
                    self.first_event = False
                    await asyncio.sleep(0.07)
                    return FakeStepDelta("first")
                return await super().__anext__()

        gemini_service.config.GEMINI_TIMEOUT_SECONDS = 0.1
        stream = DelayedThenHangingStream()

        async def accept_interaction(_kwargs):
            return types.SimpleNamespace(id="accepted-id", status="in_progress")

        client = self.set_client(accept_interaction)
        client.aio.interactions.get_handler = lambda _kwargs: _return(stream)
        client.aio.interactions.status_handler = lambda _kwargs: _return(
            types.SimpleNamespace(id="accepted-id", status="failed", output_text="")
        )
        started_at = asyncio.get_running_loop().time()
        received = [
            item
            async for item in gemini_service.chat_stream("test message")
            if item[0] != "heartbeat"
        ]
        elapsed = asyncio.get_running_loop().time() - started_at

        self.assertEqual(received[0], ("chunk", "first"))
        self.assertEqual(received[1][0], "error")
        self.assertGreaterEqual(elapsed, 0.15)
        self.assertLess(elapsed, 0.3)
        self.assertTrue(stream.closed)

    async def test_normal_stream_returns_all_chunks_and_final_interaction_id(self) -> None:
        stream = FakeStream(
            [
                FakeStepDelta("first"),
                FakeStepDelta(" second", index=1),
                FakeInteractionCompletedEvent("final-id"),
            ]
        )

        async def accept_interaction(_kwargs):
            return types.SimpleNamespace(id="accepted-id", status="in_progress")

        client = self.set_client(accept_interaction)
        client.aio.interactions.get_handler = lambda _kwargs: _return(stream)
        client.aio.interactions.status_handler = lambda _kwargs: _return(
            types.SimpleNamespace(
                id="final-id",
                status="completed",
                output_text="first second",
            )
        )
        received = [item async for item in gemini_service.chat_stream("test message")]

        self.assertEqual(
            received,
            [("chunk", "first"), ("chunk", " second"), ("done", "final-id")],
        )
        self.assertTrue(stream.closed)

    async def test_follow_up_passes_exact_previous_interaction_id(self) -> None:
        async def return_interaction(_kwargs):
            return types.SimpleNamespace(output_text="reply", id="next-id", status="in_progress")

        client = self.set_client(return_interaction)
        client.aio.interactions.get_handler = lambda _kwargs: _return(
            types.SimpleNamespace(output_text="reply", id="next-id", status="completed")
        )
        previous_id = "previous-id-test"
        result = await gemini_service.chat("test message", previous_id)

        self.assertEqual(result, ("reply", "next-id"))
        self.assertEqual(
            client.interactions.calls[0]["previous_interaction_id"], previous_id
        )

    async def test_client_configuration_disables_sdk_retries(self) -> None:
        original_key = gemini_service.config.GEMINI_API_KEY
        gemini_service.config.GEMINI_API_KEY = "test-only-key"
        try:
            gemini_service.init_client()
            retry_options = gemini_service._client._api_client._http_options.retry_options
            self.assertEqual(retry_options.attempts, 1)
        finally:
            gemini_service.config.GEMINI_API_KEY = original_key

    async def test_non_stream_timeout_maps_to_http_504(self) -> None:
        async def timeout_chat(*_args, **_kwargs):
            raise gemini_service.GeminiTimeoutError("deadline reached")

        original_chat = main.gemini_service.chat
        main.gemini_service.chat = timeout_chat
        try:
            with self.assertRaises(HTTPException) as raised:
                await main.chat(ChatRequest(message="test message"))
        finally:
            main.gemini_service.chat = original_chat

        self.assertEqual(raised.exception.status_code, 504)

    async def test_stream_timeout_maps_to_safe_sse_error(self) -> None:
        stream = FakeStream([], hang_after_events=True)

        async def accept_interaction(_kwargs):
            return types.SimpleNamespace(id="accepted-id", status="in_progress")

        client = self.set_client(accept_interaction)
        client.aio.interactions.get_handler = lambda _kwargs: _return(stream)
        client.aio.interactions.status_handler = lambda _kwargs: _return(
            types.SimpleNamespace(id="accepted-id", status="failed", output_text="")
        )
        response = await main.chat_stream(ChatRequest(message="test message"), object())
        events = [chunk async for chunk in response.body_iterator]
        data_event = next(event for event in events if event.startswith("data: "))
        payload = json.loads(data_event.removeprefix("data: ").strip())

        self.assertEqual(payload["type"], "error")
        self.assertNotIn("test message", payload["message"])
        self.assertTrue(stream.closed)


if __name__ == "__main__":
    unittest.main()
