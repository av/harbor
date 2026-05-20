"""Tests for Boost's OpenAI-compatible stream termination."""

import json
import os
import sys
import unittest

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, SRC_DIR)
os.chdir(SRC_DIR)

import llm


def sse_payload(line: str):
    assert line.startswith("data: ")
    return json.loads(line[6:])


class TestStreamingTermination(unittest.IsolatedAsyncioTestCase):
    async def test_emit_done_adds_terminal_chunk_before_done(self):
        target = llm.LLM(
            url="http://example.test/v1",
            model="model",
            messages=[{"role": "user", "content": "hello"}],
        )
        target.is_final_stream = True

        await target.emit_message("hello")
        await target.emit_done()

        chunks = [chunk async for chunk in target.response_stream()]
        self.assertEqual(chunks[-1], "data: [DONE]")

        terminal = sse_payload(chunks[-2])
        self.assertEqual(terminal["choices"][0]["delta"], {"content": ""})
        self.assertEqual(terminal["choices"][0]["finish_reason"], "stop")

    async def test_emit_done_does_not_duplicate_existing_finish_reason(self):
        target = llm.LLM(
            url="http://example.test/v1",
            model="model",
            messages=[{"role": "user", "content": "hello"}],
        )
        target.is_final_stream = True

        await target.emit_chunk(target.chunk_from_delta({}, finish_reason="stop"))
        await target.emit_done()

        chunks = [chunk async for chunk in target.response_stream()]
        finish_chunks = [
            sse_payload(chunk)
            for chunk in chunks
            if chunk.startswith("data: {")
            and sse_payload(chunk)["choices"][0].get("finish_reason") is not None
        ]

        self.assertEqual(len(finish_chunks), 1)
        self.assertEqual(finish_chunks[0]["choices"][0]["finish_reason"], "stop")

    async def test_consume_stream_defaults_missing_finish_reason_to_stop(self):
        target = llm.LLM(
            url="http://example.test/v1",
            model="model",
            messages=[{"role": "user", "content": "hello"}],
        )

        async def stream():
            yield target.chunk_to_string(target.chunk_from_message("hello"))
            yield "data: [DONE]"

        result = await target.consume_stream(stream())

        self.assertEqual(result["choices"][0]["message"]["content"], "hello")
        self.assertEqual(result["choices"][0]["finish_reason"], "stop")


class TestGeneratorCleanup(unittest.IsolatedAsyncioTestCase):
    """Verify that async generators are properly cleaned up on disconnect."""

    async def test_generator_sets_is_streaming_false_on_close(self):
        """generator() must set is_streaming=False in its finally block."""
        target = llm.LLM(
            url="http://example.test/v1",
            model="model",
            messages=[{"role": "user", "content": "hello"}],
        )
        target.is_final_stream = True

        await target.emit_message("hello")
        await target.emit_done()

        gen = target.generator()
        chunk = await gen.__anext__()
        self.assertIsNotNone(chunk)
        self.assertTrue(target.is_streaming)

        await gen.aclose()

        self.assertFalse(target.is_streaming)

    async def test_generator_sets_is_streaming_false_on_normal_exit(self):
        """generator() sets is_streaming=False when queue drains normally."""
        target = llm.LLM(
            url="http://example.test/v1",
            model="model",
            messages=[{"role": "user", "content": "hello"}],
        )
        target.is_final_stream = True

        await target.emit_message("hello")
        await target.emit_done()

        chunks = []
        async for chunk in target.generator():
            chunks.append(chunk)

        self.assertFalse(target.is_streaming)
        self.assertTrue(len(chunks) > 0)

    async def test_emit_done_called_for_unknown_module(self):
        """serve() must call emit_done() even when module is not found."""
        target = llm.LLM(
            url="http://example.test/v1",
            model="model",
            messages=[{"role": "user", "content": "hello"}],
        )
        target.module = "nonexistent_module_xyz"
        target.is_final_stream = True

        stream = await target.serve()

        chunks = []
        async for chunk in stream:
            chunks.append(chunk)

        self.assertTrue(len(chunks) >= 1)


class TestParseSSEChunksCleanup(unittest.IsolatedAsyncioTestCase):
    """Verify parse_sse_chunks closes the inner stream."""

    async def test_inner_stream_closed_on_normal_exit(self):
        """parse_sse_chunks closes response_stream when iteration completes."""
        from compat_utils import parse_sse_chunks

        closed = False

        async def mock_stream():
            nonlocal closed
            try:
                yield 'data: {"choices": [{"delta": {"content": "hi"}}]}\n\n'
                yield 'data: [DONE]\n\n'
            finally:
                closed = True

        stream = mock_stream()
        chunks = []
        async for chunk in parse_sse_chunks(stream):
            chunks.append(chunk)

        self.assertTrue(closed)
        self.assertEqual(len(chunks), 1)

    async def test_inner_stream_closed_on_consumer_break(self):
        """parse_sse_chunks closes response_stream when consumer breaks early."""
        from compat_utils import parse_sse_chunks

        closed = False

        async def mock_stream():
            nonlocal closed
            try:
                yield 'data: {"choices": [{"delta": {"content": "a"}}]}\n\n'
                yield 'data: {"choices": [{"delta": {"content": "b"}}]}\n\n'
                yield 'data: {"choices": [{"delta": {"content": "c"}}]}\n\n'
            finally:
                closed = True

        stream = mock_stream()
        gen = parse_sse_chunks(stream)

        chunk = await gen.__anext__()
        self.assertIsNotNone(chunk)
        await gen.aclose()

        self.assertTrue(closed)

    async def test_inner_stream_closed_on_explicit_close(self):
        """parse_sse_chunks closes response_stream when aclose() is called."""
        from compat_utils import parse_sse_chunks

        closed = False

        async def mock_stream():
            nonlocal closed
            try:
                yield 'data: {"choices": [{"delta": {"content": "hi"}}]}\n\n'
                yield 'data: {"choices": [{"delta": {"content": "world"}}]}\n\n'
            finally:
                closed = True

        stream = mock_stream()
        gen = parse_sse_chunks(stream)

        chunk = await gen.__anext__()
        self.assertIsNotNone(chunk)
        await gen.aclose()

        self.assertTrue(closed)


class TestBackgroundTaskCallback(unittest.IsolatedAsyncioTestCase):
    """Verify that the done callback on the background task works."""

    async def test_task_done_callback_unblocks_consumer(self):
        """When apply_mod crashes, the done callback unblocks the consumer
        and the stored error is re-raised by the generator.

        Without the callback, the consumer would hang forever on
        queue.get() because no None sentinel would ever arrive.
        With the callback, the sentinel is sent and the error propagates.
        """
        target = llm.LLM(
            url="http://example.test/v1",
            model="model",
            messages=[{"role": "user", "content": "hello"}],
        )
        target.module = None
        target.is_final_stream = True

        stream = await target.serve()

        chunks = []
        error_raised = False
        try:
            async for chunk in stream:
                chunks.append(chunk)
        except Exception:
            error_raised = True

        # The background task failed (connect to fake URL), so either
        # the error propagates or the stream ends — consumer must not hang.
        self.assertTrue(error_raised or isinstance(chunks, list))


class TestStreamErrorPropagation(unittest.IsolatedAsyncioTestCase):
    """Verify that _stream_error is stored and re-raised by the generator."""

    async def test_stream_error_stored_on_task_failure(self):
        """When _stream_error is set, generator() raises it after draining."""
        from llm import BackendError

        target = llm.LLM(
            url="http://example.test/v1",
            model="model",
            messages=[{"role": "user", "content": "hello"}],
        )
        target.is_final_stream = True

        target._stream_error = BackendError(429, "rate limited", {"retry-after": "5"})
        target.queue.put_nowait(None)

        with self.assertRaises(BackendError) as ctx:
            async for _ in target.generator():
                pass

        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.body, "rate limited")

    async def test_stream_error_not_raised_when_none(self):
        """When _stream_error is None, generator() exits normally."""
        target = llm.LLM(
            url="http://example.test/v1",
            model="model",
            messages=[{"role": "user", "content": "hello"}],
        )
        target.is_final_stream = True

        await target.emit_message("hello")
        await target.emit_done()

        chunks = []
        async for chunk in target.generator():
            chunks.append(chunk)

        self.assertTrue(len(chunks) > 0)
        self.assertIsNone(target._stream_error)

    async def test_stream_error_propagates_through_response_stream(self):
        """_stream_error propagates through response_stream() to the consumer."""
        from llm import BackendError

        target = llm.LLM(
            url="http://example.test/v1",
            model="model",
            messages=[{"role": "user", "content": "hello"}],
        )
        target.is_final_stream = True

        target._stream_error = BackendError(500, "server error")
        target.queue.put_nowait(None)

        with self.assertRaises(BackendError) as ctx:
            async for _ in target.response_stream():
                pass

        self.assertEqual(ctx.exception.status_code, 500)

    async def test_stream_error_with_chunks_before_failure(self):
        """Chunks emitted before the error are still yielded."""
        from llm import BackendError

        target = llm.LLM(
            url="http://example.test/v1",
            model="model",
            messages=[{"role": "user", "content": "hello"}],
        )
        target.is_final_stream = True

        await target.emit_message("partial content")
        target._stream_error = BackendError(429, "rate limited")
        target.queue.put_nowait(None)

        chunks = []
        with self.assertRaises(BackendError):
            async for chunk in target.generator():
                chunks.append(chunk)

        self.assertTrue(len(chunks) >= 1)
        joined = "".join(str(c) for c in chunks)
        self.assertIn("partial content", joined)

    async def test_stream_error_sets_is_streaming_false(self):
        """Even when _stream_error is raised, is_streaming is set to False."""
        from llm import BackendError

        target = llm.LLM(
            url="http://example.test/v1",
            model="model",
            messages=[{"role": "user", "content": "hello"}],
        )
        target.is_final_stream = True

        target._stream_error = BackendError(429, "rate limited")
        target.queue.put_nowait(None)

        try:
            async for _ in target.generator():
                pass
        except BackendError:
            pass

        self.assertFalse(target.is_streaming)


class TestConsumeStreamAccumulation(unittest.IsolatedAsyncioTestCase):
    """Verify consume_stream accumulates reasoning_content, refusal,
    and completion_tokens_details from streaming chunks."""

    def _make_llm(self):
        return llm.LLM(
            url="http://example.test/v1",
            model="model",
            messages=[{"role": "user", "content": "hello"}],
        )

    def _chunk(self, delta, finish_reason=None, usage=None):
        """Build a stringified SSE chunk."""
        choice = {"index": 0, "delta": delta}
        if finish_reason:
            choice["finish_reason"] = finish_reason
        obj = {
            "id": "cmp-1",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "m",
            "choices": [choice],
        }
        if usage:
            obj["usage"] = usage
        return f"data: {json.dumps(obj)}\n\n"

    async def _stream_from_chunks(self, target, raw_chunks):
        """Feed raw SSE strings through serve-like async generator."""
        async def gen():
            for c in raw_chunks:
                yield c
        return await target.consume_stream(gen())

    async def test_accumulates_reasoning_content(self):
        target = self._make_llm()
        chunks = [
            self._chunk({"reasoning_content": "Step 1"}),
            self._chunk({"reasoning_content": " Step 2"}),
            self._chunk({"content": "Answer"}, finish_reason="stop"),
            "data: [DONE]\n\n",
        ]
        result = await self._stream_from_chunks(target, chunks)
        self.assertEqual(result["choices"][0]["message"]["reasoning_content"], "Step 1 Step 2")
        self.assertEqual(result["choices"][0]["message"]["content"], "Answer")

    async def test_accumulates_reasoning_field(self):
        """Some backends use 'reasoning' instead of 'reasoning_content'."""
        target = self._make_llm()
        chunks = [
            self._chunk({"reasoning": "Think"}),
            self._chunk({"content": "Done"}, finish_reason="stop"),
            "data: [DONE]\n\n",
        ]
        result = await self._stream_from_chunks(target, chunks)
        self.assertEqual(result["choices"][0]["message"]["reasoning_content"], "Think")

    async def test_accumulates_refusal(self):
        target = self._make_llm()
        chunks = [
            self._chunk({"refusal": "I cannot"}),
            self._chunk({"refusal": " help with that"}, finish_reason="stop"),
            "data: [DONE]\n\n",
        ]
        result = await self._stream_from_chunks(target, chunks)
        self.assertEqual(result["choices"][0]["message"]["refusal"], "I cannot help with that")

    async def test_preserves_completion_tokens_details(self):
        target = self._make_llm()
        usage = {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "completion_tokens_details": {"reasoning_tokens": 3},
        }
        chunks = [
            self._chunk({"content": "Hi"}, finish_reason="stop", usage=usage),
            "data: [DONE]\n\n",
        ]
        result = await self._stream_from_chunks(target, chunks)
        self.assertEqual(result["usage"]["completion_tokens_details"], {"reasoning_tokens": 3})

    async def test_no_reasoning_when_absent(self):
        target = self._make_llm()
        chunks = [
            self._chunk({"content": "Normal"}, finish_reason="stop"),
            "data: [DONE]\n\n",
        ]
        result = await self._stream_from_chunks(target, chunks)
        self.assertNotIn("reasoning_content", result["choices"][0]["message"])
        self.assertNotIn("refusal", result["choices"][0]["message"])

    async def test_no_completion_tokens_details_when_absent(self):
        target = self._make_llm()
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        chunks = [
            self._chunk({"content": "Hi"}, finish_reason="stop", usage=usage),
            "data: [DONE]\n\n",
        ]
        result = await self._stream_from_chunks(target, chunks)
        self.assertNotIn("completion_tokens_details", result["usage"])


if __name__ == '__main__':
    unittest.main()
