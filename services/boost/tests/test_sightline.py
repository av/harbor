"""Unit tests for the sightline Boost module."""

import asyncio
import json
import os
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
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


class TestSightlineWorkspace:
  def test_workspace_guard_disabled_without_root(self):
    original_root = config.WORKSPACE_ROOT.__value__
    original_workspace = config.SIGHTLINE_WORKSPACE.__value__
    try:
      config.WORKSPACE_ROOT.__value__ = ""
      config.SIGHTLINE_WORKSPACE.__value__ = True
      assert not sightline.workspace_guard_enabled()
      assert not sightline.workspace_guard_enabled(workspace=True)
    finally:
      config.WORKSPACE_ROOT.__value__ = original_root
      config.SIGHTLINE_WORKSPACE.__value__ = original_workspace

  def test_workspace_guard_enabled_when_root_configured(self):
    original_root = config.WORKSPACE_ROOT.__value__
    original_workspace = config.SIGHTLINE_WORKSPACE.__value__
    try:
      config.WORKSPACE_ROOT.__value__ = "/workspace"
      config.SIGHTLINE_WORKSPACE.__value__ = True
      assert sightline.workspace_guard_enabled()
    finally:
      config.WORKSPACE_ROOT.__value__ = original_root
      config.SIGHTLINE_WORKSPACE.__value__ = original_workspace

  def test_workspace_guard_respects_config_flag(self):
    original_root = config.WORKSPACE_ROOT.__value__
    original_workspace = config.SIGHTLINE_WORKSPACE.__value__
    try:
      config.WORKSPACE_ROOT.__value__ = "/workspace"
      config.SIGHTLINE_WORKSPACE.__value__ = False
      assert not sightline.workspace_guard_enabled()
      assert sightline.workspace_guard_enabled(workspace=True)
    finally:
      config.WORKSPACE_ROOT.__value__ = original_root
      config.SIGHTLINE_WORKSPACE.__value__ = original_workspace

  def test_workspace_canonical_path_uses_prefix(self):
    with tempfile.TemporaryDirectory() as workspace:
      target = Path(workspace) / "src" / "main.py"
      target.parent.mkdir(parents=True)
      target.write_text("print('ok')", encoding="utf-8")

      original_root = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = workspace
        canonical = sightline.workspace_canonical_path("src/main.py")
      finally:
        config.WORKSPACE_ROOT.__value__ = original_root

    assert canonical == "workspace:src/main.py"

  def test_workspace_block_message_uses_workspace_tools(self):
    message = sightline.block_message("src/main.py", 2, 1, kind="workspace")
    payload = json.loads(message)
    assert payload["required_tool"] == "read_workspace_file"
    assert payload["tool_kind"] == "workspace"
    assert payload["canonical_path"] == "workspace:src/main.py"

  @pytest.mark.asyncio
  async def test_read_workspace_file_records_generation(self):
    with tempfile.TemporaryDirectory() as workspace:
      target = Path(workspace) / "tracked.py"
      target.write_text("version 1", encoding="utf-8")

      original_root = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = workspace
        with request_context():
          llm = MagicMock()
          llm.emit_status = AsyncMock()
          tool_registry.set_local_tool(
            "read_workspace_file",
            tools_module.read_workspace_file,
          )
          sightline.install_guards(llm)

          read_tool = tool_registry.get_local_tool("read_workspace_file")
          await read_tool("tracked.py")

          path = sightline.workspace_canonical_path("tracked.py")
          read_gen, write_gen = sightline.get_generations(path)
          assert read_gen > write_gen
      finally:
        config.WORKSPACE_ROOT.__value__ = original_root

  @pytest.mark.asyncio
  async def test_write_workspace_file_blocked_without_prior_read(self):
    async def write_workspace_file(file_path: str, content: str) -> str:
      target = tools_module._workspace_path(file_path)
      target.parent.mkdir(parents=True, exist_ok=True)
      target.write_text(content, encoding="utf-8")
      return f"Wrote {len(content)} characters to {file_path}."

    with tempfile.TemporaryDirectory() as workspace:
      target = Path(workspace) / "blocked.py"
      target.write_text("seed", encoding="utf-8")

      original_root = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = workspace
        with request_context():
          llm = MagicMock()
          llm.emit_status = AsyncMock()
          tool_registry.set_local_tool("write_workspace_file", write_workspace_file)
          sightline.install_guards(llm)

          write_tool = tool_registry.get_local_tool("write_workspace_file")
          with pytest.raises(ValueError, match="sightline_read_required"):
            await write_tool("blocked.py", "content")

          llm.emit_status.assert_awaited_once()
          assert "read_workspace_file required" in llm.emit_status.await_args.args[0]
      finally:
        config.WORKSPACE_ROOT.__value__ = original_root

  @pytest.mark.asyncio
  async def test_write_workspace_file_allowed_after_read(self):
    async def write_workspace_file(file_path: str, content: str) -> str:
      target = tools_module._workspace_path(file_path)
      target.parent.mkdir(parents=True, exist_ok=True)
      target.write_text(content, encoding="utf-8")
      return f"Wrote {len(content)} characters to {file_path}."

    with tempfile.TemporaryDirectory() as workspace:
      original_root = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = workspace
        with request_context():
          llm = MagicMock()
          llm.emit_status = AsyncMock()
          tool_registry.set_local_tool(
            "read_workspace_file",
            tools_module.read_workspace_file,
          )
          tool_registry.set_local_tool("write_workspace_file", write_workspace_file)
          sightline.install_guards(llm)

          write_tool = tool_registry.get_local_tool("write_workspace_file")
          read_tool = tool_registry.get_local_tool("read_workspace_file")

          await write_tool("draft.py", "first version")
          await read_tool("draft.py")
          result = await write_tool("draft.py", "second version")

          assert "second version" in result or "Wrote" in result
      finally:
        config.WORKSPACE_ROOT.__value__ = original_root

  @pytest.mark.asyncio
  async def test_workspace_guards_skipped_when_disabled(self):
    with tempfile.TemporaryDirectory() as workspace:
      original_root = config.WORKSPACE_ROOT.__value__
      original_workspace = config.SIGHTLINE_WORKSPACE.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = workspace
        config.SIGHTLINE_WORKSPACE.__value__ = False
        with request_context():
          llm = MagicMock()
          llm.emit_status = AsyncMock()
          tool_registry.set_local_tool(
            "read_workspace_file",
            tools_module.read_workspace_file,
          )
          wrapped = sightline.install_guards(llm, workspace=False)

          assert "read_workspace_file" not in wrapped
          read_tool = tool_registry.get_local_tool("read_workspace_file")
          assert not getattr(read_tool, "_sightline_wrapped", False)
      finally:
        config.WORKSPACE_ROOT.__value__ = original_root
        config.SIGHTLINE_WORKSPACE.__value__ = original_workspace


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
  async def test_apply_wraps_workspace_reader_when_configured(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Inspect workspace files carefully."},
    ])
    llm = MagicMock()
    llm.stream_final_completion = AsyncMock()

    with tempfile.TemporaryDirectory() as workspace:
      original_root = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = workspace
        with request_context():
          tool_registry.set_local_tool(
            "read_workspace_file",
            tools_module.read_workspace_file,
          )

          await sightline.apply(chat, llm, config={"final": True})

          read_tool = tool_registry.get_local_tool("read_workspace_file")
          assert getattr(read_tool, "_sightline_wrapped", False)
      finally:
        config.WORKSPACE_ROOT.__value__ = original_root

    history = chat.history()
    assert any("read_workspace_file" in (msg.get("content") or "") for msg in history)
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

  @pytest.mark.asyncio
  async def test_apply_respects_workflow_injected_defer_final(self):
    """Workflow chains inject defer_final when final is unset; sightline must not stream."""
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Edit scratch notes carefully."},
    ])
    llm = MagicMock()
    llm.stream_final_completion = AsyncMock()

    with request_context():
      tool_registry.set_local_tool("write_file", tools_module.write_file)
      tool_registry.set_local_tool("read_file", tools_module.read_file)

      await sightline.apply(chat, llm, config={"defer_final": True})

    llm.stream_final_completion.assert_not_awaited()