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
        """When apply_mod crashes, the done callback unblocks the consumer.

        Without the callback, the consumer would hang forever on
        queue.get() because no None sentinel would ever arrive.
        With the callback, the sentinel is sent and the stream terminates.
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
        async for chunk in stream:
            chunks.append(chunk)

        self.assertIsInstance(chunks, list)


if __name__ == '__main__':
    unittest.main()
