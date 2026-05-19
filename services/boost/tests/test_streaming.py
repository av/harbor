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


if __name__ == '__main__':
    unittest.main()
