"""Mocked tests for background Interactions API execution.

No dotenv file is loaded and no network requests are made from these tests.
"""

from __future__ import annotations

import asyncio
import dotenv
import json
import types
import unittest

dotenv.load_dotenv = lambda *args, **kwargs: None

from fastapi import HTTPException

from app import gemini_service, main
from app.schemas import ChatRequest


class FakeTextDelta:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeStepDelta:
    def __init__(self, text: str) -> None:
        self.delta = FakeTextDelta(text)
        self.index = 0
        self.event_type = "step.delta"


class FakeCompleted:
    def __init__(self, interaction_id: str, status: str) -> None:
        self.interaction = types.SimpleNamespace(id=interaction_id, status=status)
        self.event_type = "interaction.completed"


class FakeStream:
    def __init__(self, events=(), *, hang=False) -> None:
        self.events = iter(events)
        self.hang = hang
        self.closed = False
        self.cancelled = False
        self.never = asyncio.Event()

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.events)
        except StopIteration:
            if not self.hang:
                raise StopAsyncIteration
            try:
                await self.never.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
            raise AssertionError("fake stream should remain pending")

    async def aclose(self):
        self.closed = True


class FakeInteractions:
    def __init__(self) -> None:
        self.create_result = None
        self.get_result = None
        self.stream_result = None
        self.cancel_result = None
        self.create_calls = []
        self.get_calls = []
        self.cancel_calls = []

    async def create(self, **kwargs):
        self.create_calls.append(kwargs)
        if isinstance(self.create_result, BaseException):
            raise self.create_result
        return self.create_result

    async def get(self, *, id, stream=False, **kwargs):
        self.get_calls.append({"id": id, "stream": stream, **kwargs})
        if stream:
            if isinstance(self.stream_result, BaseException):
                raise self.stream_result
            return self.stream_result
        if isinstance(self.get_result, BaseException):
            raise self.get_result
        return self.get_result

    async def cancel(self, *, id, **kwargs):
        self.cancel_calls.append({"id": id, **kwargs})
        if isinstance(self.cancel_result, BaseException):
            raise self.cancel_result
        return self.cancel_result


class FakeClient:
    def __init__(self) -> None:
        self.interactions = FakeInteractions()
        self.aio = types.SimpleNamespace(interactions=self.interactions)


class BackgroundInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_client = gemini_service._client
        self.original_timeout = gemini_service.config.GEMINI_TIMEOUT_SECONDS
        self.original_generation_config = gemini_service.config.GEMINI_GENERATION_CONFIG
        self.original_step_delta = gemini_service.StepDelta
        self.original_text_delta = gemini_service.TextDelta
        self.original_completed_event = gemini_service.InteractionCompletedEvent
        gemini_service.config.GEMINI_TIMEOUT_SECONDS = 0.05
        gemini_service.StepDelta = FakeStepDelta
        gemini_service.TextDelta = FakeTextDelta
        gemini_service.InteractionCompletedEvent = FakeCompleted
        self.client = FakeClient()
        gemini_service._client = self.client

    async def asyncTearDown(self) -> None:
        gemini_service._client = self.original_client
        gemini_service.config.GEMINI_TIMEOUT_SECONDS = self.original_timeout
        gemini_service.config.GEMINI_GENERATION_CONFIG = self.original_generation_config
        gemini_service.StepDelta = self.original_step_delta
        gemini_service.TextDelta = self.original_text_delta
        gemini_service.InteractionCompletedEvent = self.original_completed_event

    def interaction(self, *, id="interaction-1", status="in_progress", output_text=None, errors=None):
        return types.SimpleNamespace(
            id=id,
            status=status,
            output_text=output_text,
            errors=errors,
            model="gemini-3.8-flash",
        )

    async def test_background_create_returns_actual_id_and_in_progress(self) -> None:
        self.client.interactions.create_result = self.interaction()
        created = await gemini_service.start_background_interaction("hello", None)

        self.assertEqual(created.id, "interaction-1")
        self.assertEqual(created.status, "in_progress")
        self.assertIs(self.client.interactions.create_calls[0]["background"], True)
        self.assertIs(self.client.interactions.create_calls[0]["store"], True)

    async def test_get_reports_in_progress_status(self) -> None:
        self.client.interactions.get_result = self.interaction(status="queued")
        current = await gemini_service.get_background_interaction("interaction-1")
        self.assertEqual(current.status, "queued")
        self.assertEqual(self.client.interactions.get_calls[0]["id"], "interaction-1")

    async def test_completed_interaction_returns_final_output_and_id(self) -> None:
        self.client.interactions.get_result = self.interaction(
            status="completed", output_text="finished response"
        )
        current = await gemini_service.get_background_interaction("interaction-1")
        self.assertEqual(current.output_text, "finished response")
        self.assertEqual(current.id, "interaction-1")

    async def test_failed_and_cancelled_statuses_are_safely_classified(self) -> None:
        for status in ("failed", "cancelled", "incomplete", "budget_exceeded", "requires_action"):
            current = self.interaction(status=status, errors=[types.SimpleNamespace(message="private detail")])
            result = gemini_service.classify_interaction_status(current)
            self.assertEqual(result, "error", status)
            self.assertNotIn("private detail", gemini_service.interaction_error_message(current))

    async def test_follow_up_uses_exact_completed_interaction_id(self) -> None:
        self.client.interactions.create_result = self.interaction(id="next-id", status="queued")
        self.client.interactions.get_result = self.interaction(status="completed")
        previous_id = "actual-completed-id"
        await gemini_service.start_background_interaction("follow up", previous_id)
        self.assertEqual(
            self.client.interactions.create_calls[0]["previous_interaction_id"],
            previous_id,
        )

    async def test_system_instruction_and_generation_config_are_sent_each_turn(self) -> None:
        config = {"temperature": 0.2}
        gemini_service.config.GEMINI_GENERATION_CONFIG = config
        self.client.interactions.create_result = self.interaction()
        self.client.interactions.get_result = self.interaction(status="completed")
        await gemini_service.start_background_interaction("follow up", "completed-id")
        call = self.client.interactions.create_calls[0]
        self.assertEqual(call["system_instruction"], gemini_service.config.JARVIS_SYSTEM_INSTRUCTION)
        self.assertEqual(call["generation_config"], config)

    async def test_follow_up_rejects_an_in_progress_parent(self) -> None:
        self.client.interactions.get_result = self.interaction(status="in_progress")
        with self.assertRaises(gemini_service.GeminiUpstreamError):
            await gemini_service.start_background_interaction("follow up", "active-id")
        self.assertEqual(self.client.interactions.create_calls, [])

    async def test_background_stream_returns_chunks_and_closes(self) -> None:
        stream = FakeStream([FakeStepDelta("a"), FakeStepDelta("b"), FakeCompleted("interaction-1", "completed")])
        self.client.interactions.stream_result = stream
        self.client.interactions.get_result = self.interaction(
            status="completed", output_text="ab"
        )
        events = [event async for event in gemini_service.stream_background_interaction("interaction-1")]
        self.assertEqual(events, [("chunk", "a"), ("chunk", "b"), ("done", "interaction-1")])
        self.assertTrue(stream.closed)
        self.assertEqual(self.client.interactions.get_calls[0]["stream"], True)

    async def test_hung_background_stream_falls_back_to_status_polling(self) -> None:
        stream = FakeStream(hang=True)
        self.client.interactions.stream_result = stream
        self.client.interactions.get_result = self.interaction(
            status="completed", output_text="completed response"
        )
        events = [event async for event in gemini_service.stream_background_interaction("interaction-1")]

        self.assertIn(("replace", "completed response"), events)
        self.assertEqual(events[-1], ("done", "interaction-1"))
        self.assertTrue(stream.cancelled)
        self.assertTrue(stream.closed)
        self.assertTrue(any(call["stream"] is False for call in self.client.interactions.get_calls))

    async def test_streaming_get_may_return_completed_interaction_directly(self) -> None:
        self.client.interactions.stream_result = self.interaction(
            id="finished-id",
            status="completed",
            output_text="complete answer",
        )
        events = [event async for event in gemini_service.stream_background_interaction("interaction-1")]
        self.assertEqual(
            events,
            [("replace", "complete answer"), ("done", "finished-id")],
        )

    async def test_cancel_calls_sdk_and_stream_cancellation_closes_resources(self) -> None:
        self.client.interactions.cancel_result = self.interaction(status="cancelled")
        await gemini_service.cancel_background_interaction("interaction-1")
        self.assertEqual(self.client.interactions.cancel_calls[0]["id"], "interaction-1")

        stream = FakeStream(hang=True)
        self.client.interactions.stream_result = stream
        generator = gemini_service.stream_background_interaction("interaction-2")
        task = asyncio.create_task(anext(generator))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await generator.aclose()
        self.assertTrue(stream.closed)
        self.assertTrue(stream.cancelled)

    async def test_sse_heartbeat_wrapper_cancels_pending_event_task(self) -> None:
        closed = False

        async def never_emits():
            nonlocal closed
            try:
                await asyncio.Event().wait()
                yield ("done", "id")
            finally:
                closed = True

        wrapped = main._stream_with_heartbeats(never_emits(), interval_seconds=1.0)
        pending = asyncio.create_task(anext(wrapped))
        await asyncio.sleep(0)
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        await wrapped.aclose()
        self.assertTrue(closed)

    async def test_timeout_and_upstream_errors_are_classified(self) -> None:
        self.client.interactions.create_result = asyncio.TimeoutError()
        with self.assertRaises(gemini_service.GeminiTimeoutError):
            await gemini_service.start_background_interaction("hello", None)

        self.client.interactions.get_result = RuntimeError("sensitive response text")
        with self.assertRaises(gemini_service.GeminiUpstreamError) as raised:
            await gemini_service.get_background_interaction("interaction-1")
        self.assertNotIn("sensitive response text", str(raised.exception))

    async def test_start_endpoint_returns_without_polling_for_completion(self) -> None:
        self.client.interactions.create_result = self.interaction(status="in_progress")
        response = await main.start_interaction(ChatRequest(message="hello"))
        self.assertEqual(response["interaction_id"], "interaction-1")
        self.assertEqual(response["status"], "in_progress")
        self.assertEqual(len(self.client.interactions.get_calls), 0)

    async def test_status_endpoint_includes_reply_only_when_completed(self) -> None:
        self.client.interactions.get_result = self.interaction(status="in_progress")
        in_progress = await main.interaction_status("interaction-1")
        self.assertEqual(in_progress["status"], "in_progress")
        self.assertNotIn("reply", in_progress)

        self.client.interactions.get_result = self.interaction(status="completed", output_text="done")
        completed = await main.interaction_status("interaction-1")
        self.assertEqual(completed["reply"], "done")

        for status in ("failed", "cancelled"):
            self.client.interactions.get_result = self.interaction(
                status=status,
                errors=[types.SimpleNamespace(message="sensitive upstream detail")],
            )
            terminal = await main.interaction_status("interaction-1")
            self.assertEqual(terminal["status"], status)
            self.assertIn("error", terminal)
            self.assertNotIn("sensitive upstream detail", terminal["error"])

    async def test_legacy_http_chat_timeout_maps_to_504(self) -> None:
        async def timeout_chat(*_args, **_kwargs):
            raise gemini_service.GeminiTimeoutError("deadline")

        original = gemini_service.chat
        gemini_service.chat = timeout_chat
        try:
            with self.assertRaises(HTTPException) as raised:
                await main.chat(ChatRequest(message="hello"))
        finally:
            gemini_service.chat = original
        self.assertEqual(raised.exception.status_code, 504)


if __name__ == "__main__":
    unittest.main()
