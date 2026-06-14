"""Unit tests for the sightline Boost module."""

import asyncio
import json
import os
import sys
import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chat as ch
import config
import tools.registry as tool_registry
from middleware.request_id import request_id_var
from modules import sightline
from modules import tools as tools_module
from state import request as request_state


@contextmanager
def request_context(request_id: str | None = None):
  request_id = request_id or f"sightline-{uuid.uuid4().hex[:8]}"
  req = MagicMock()
  req.state = type("State", (), {})()
  token_req = request_state.set(req)
  token_id = request_id_var.set(request_id)
  try:
    yield req
  finally:
    request_state.reset(token_req)
    request_id_var.reset(token_id)
    if hasattr(req.state, "local_tools"):
      delattr(req.state, "local_tools")
    if hasattr(req.state, "sightline_path_state"):
      delattr(req.state, "sightline_path_state")
    if hasattr(req.state, "sightline_seq"):
      delattr(req.state, "sightline_seq")


class TestSightlineGenerations:
  def test_can_mutate_requires_read_after_write(self):
    with request_context():
      assert not sightline.can_mutate("notes.txt")
      sightline.record_read("notes.txt")
      assert sightline.can_mutate("notes.txt")
      sightline.record_write("notes.txt")
      assert not sightline.can_mutate("notes.txt")

  def test_get_generations_tracks_per_path(self):
    with request_context():
      sightline.record_read("a.txt")
      sightline.record_write("a.txt")
      sightline.record_read("b.txt")

      a_read, a_write = sightline.get_generations("a.txt")
      b_read, b_write = sightline.get_generations("b.txt")

      assert a_write > 0
      assert b_read > b_write
      assert not sightline.can_mutate("a.txt")
      assert sightline.can_mutate("b.txt")

  def test_block_message_is_structured_json(self):
    message = sightline.block_message("src/main.py", 3, 1)
    payload = json.loads(message)
    assert payload["error"] == "sightline_read_required"
    assert payload["required_tool"] == "read_file"
    assert payload["path"] == "src/main.py"
    assert payload["read_generation"] == 3
    assert payload["write_generation"] == 1


class TestSightlineExemptions:
  def test_create_exempt_for_missing_scratch_file(self):
    with request_context():
      assert sightline.is_create_exempt("new-file.txt")

  def test_create_not_exempt_when_file_exists(self):
    with request_context():
      asyncio.run(tools_module.write_file("existing.txt", "hello"))
      assert not sightline.is_create_exempt("existing.txt")

  def test_create_not_exempt_when_disabled(self):
    with request_context():
      original = config.SIGHTLINE_ALLOW_CREATE.__value__
      try:
        config.SIGHTLINE_ALLOW_CREATE.__value__ = False
        assert not sightline.is_create_exempt("new-file.txt", allow_create=False)
      finally:
        config.SIGHTLINE_ALLOW_CREATE.__value__ = original


class TestSightlineGuards:
  @pytest.mark.asyncio
  async def test_write_blocked_without_prior_read(self):
    with request_context():
      llm = MagicMock()
      llm.emit_status = AsyncMock()
      await tools_module.write_file("blocked.txt", "seed")
      tool_registry.set_local_tool("write_file", tools_module.write_file)
      sightline.install_guards(llm)

      write_tool = tool_registry.get_local_tool("write_file")
      with pytest.raises(ValueError, match="sightline_read_required"):
        await write_tool("blocked.txt", "content")

      llm.emit_status.assert_awaited_once()
      assert "read_file required" in llm.emit_status.await_args.args[0]

  @pytest.mark.asyncio
  async def test_write_allowed_after_read(self):
    with request_context():
      llm = MagicMock()
      llm.emit_status = AsyncMock()
      tool_registry.set_local_tool("read_file", tools_module.read_file)
      tool_registry.set_local_tool("write_file", tools_module.write_file)
      sightline.install_guards(llm)

      write_tool = tool_registry.get_local_tool("write_file")
      read_tool = tool_registry.get_local_tool("read_file")

      await write_tool("draft.txt", "first version")
      await read_tool("draft.txt")
      result = await write_tool("draft.txt", "second version")

      assert "second version" in result or "Wrote" in result

  @pytest.mark.asyncio
  async def test_second_write_requires_fresh_read(self):
    with request_context():
      llm = MagicMock()
      llm.emit_status = AsyncMock()
      tool_registry.set_local_tool("read_file", tools_module.read_file)
      tool_registry.set_local_tool("write_file", tools_module.write_file)
      sightline.install_guards(llm)

      write_tool = tool_registry.get_local_tool("write_file")
      read_tool = tool_registry.get_local_tool("read_file")

      await write_tool("draft.txt", "seed")
      await read_tool("draft.txt")
      await write_tool("draft.txt", "first version")

      with pytest.raises(ValueError, match="sightline_read_required"):
        await write_tool("draft.txt", "second version")

  @pytest.mark.asyncio
  async def test_delete_blocked_without_prior_read(self):
    with request_context():
      llm = MagicMock()
      llm.emit_status = AsyncMock()
      tool_registry.set_local_tool("write_file", tools_module.write_file)
      tool_registry.set_local_tool("delete_file", tools_module.delete_file)
      sightline.install_guards(llm)

      write_tool = tool_registry.get_local_tool("write_file")
      delete_tool = tool_registry.get_local_tool("delete_file")

      await write_tool("remove-me.txt", "payload")

      with pytest.raises(ValueError, match="sightline_read_required"):
        await delete_tool("remove-me.txt")

  @pytest.mark.asyncio
  async def test_warn_mode_allows_mutation(self):
    with request_context():
      llm = MagicMock()
      llm.emit_status = AsyncMock()
      await tools_module.write_file("warn.txt", "seed")
      tool_registry.set_local_tool("write_file", tools_module.write_file)
      sightline.install_guards(llm, mode="warn")

      write_tool = tool_registry.get_local_tool("write_file")
      result = await write_tool("warn.txt", "allowed")

      assert "Wrote" in result
      llm.emit_status.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_read_wrapper_records_generation(self):
    with request_context():
      llm = MagicMock()
      llm.emit_status = AsyncMock()
      tool_registry.set_local_tool("write_file", tools_module.write_file)
      tool_registry.set_local_tool("read_file", tools_module.read_file)
      sightline.install_guards(llm)

      write_tool = tool_registry.get_local_tool("write_file")
      read_tool = tool_registry.get_local_tool("read_file")

      await write_tool("tracked.txt", "payload")
      await read_tool("tracked.txt")

      read_gen, write_gen = sightline.get_generations("tracked.txt")
      assert read_gen > write_gen


class TestSightlineApply:
  @pytest.mark.asyncio
  async def test_apply_wraps_tools_and_streams_final(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Edit scratch notes carefully."},
    ])
    llm = MagicMock()
    llm.stream_final_completion = AsyncMock()

    with request_context():
      tool_registry.set_local_tool("write_file", tools_module.write_file)
      tool_registry.set_local_tool("read_file", tools_module.read_file)

      await sightline.apply(chat, llm, config={"final": True})

      write_tool = tool_registry.get_local_tool("write_file")
      assert getattr(write_tool, "_sightline_wrapped", False)

    history = chat.history()
    assert any("read_file" in (msg.get("content") or "") for msg in history)
    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_apply_passes_through_when_no_tools_registered(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Hello"},
    ])
    llm = MagicMock()
    llm.stream_final_completion = AsyncMock()

    with request_context():
      await sightline.apply(chat, llm)

    llm.stream_final_completion.assert_awaited_once()