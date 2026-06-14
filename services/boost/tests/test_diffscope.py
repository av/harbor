"""Unit tests for the diffscope Boost module."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chat as ch
import config
from modules import diffscope


class TestDiffscopeGate:
  def _chat(self, *messages: str) -> ch.Chat:
    conversation = [{"role": "user", "content": msg} for msg in messages]
    return ch.Chat.from_conversation(conversation)

  def test_needs_diffscope_for_coding_deliverable(self):
    chat = self._chat("Implement retry helper in services/boost/src/utils.py")
    assert diffscope.needs_diffscope(chat)

  def test_skips_explanatory_question(self):
    chat = self._chat("Explain what asyncio.gather does in plain English.")
    assert not diffscope.needs_diffscope(chat)

  def test_skips_when_disabled(self):
    chat = self._chat("Implement foo in bar.py")
    original = config.DIFFSCOPE_ENABLED.__value__
    try:
      config.DIFFSCOPE_ENABLED.__value__ = False
      assert not diffscope.needs_diffscope(chat)
    finally:
      config.DIFFSCOPE_ENABLED.__value__ = original


class TestUserScope:
  def _chat(self, *messages: str) -> ch.Chat:
    conversation = [{"role": "user", "content": msg} for msg in messages]
    return ch.Chat.from_conversation(conversation)

  def test_extract_allowed_paths_from_only_phrase(self):
    chat = self._chat("Only change services/boost/src/utils.py for the retry helper.")
    scope = diffscope.extract_user_scope(chat)
    assert "services/boost/src/utils.py" in scope.allowed
    assert scope.has_constraints

  def test_extract_forbidden_paths_from_dont_touch(self):
    chat = self._chat("Fix the bug but don't touch services/boost/src/config.py.")
    scope = diffscope.extract_user_scope(chat)
    assert "services/boost/src/config.py" in scope.forbidden

  def test_extract_hinted_paths_from_mentions(self):
    chat = self._chat("Update services/boost/src/main.py to log errors.")
    scope = diffscope.extract_user_scope(chat)
    assert "services/boost/src/main.py" in scope.hinted
    assert not scope.allowed

  def test_recent_user_texts_limits_turns(self):
    chat = self._chat("one", "two", "three", "four", "five", "six")
    original = config.DIFFSCOPE_MAX_USER_TURNS.__value__
    try:
      config.DIFFSCOPE_MAX_USER_TURNS.__value__ = 2
      texts = diffscope.recent_user_texts(chat)
    finally:
      config.DIFFSCOPE_MAX_USER_TURNS.__value__ = original
    assert texts == ["five", "six"]


class TestResponsePaths:
  def test_extract_paths_from_backticks_and_diff(self):
    text = (
      "Edit `services/boost/src/a.py`.\n"
      "--- a/services/boost/src/b.py\n"
      "+++ b/services/boost/src/b.py\n"
      "```python:services/boost/src/c.py\nprint(1)\n```"
    )
    paths = diffscope.extract_response_paths(text)
    assert "services/boost/src/a.py" in paths
    assert "services/boost/src/b.py" in paths
    assert "services/boost/src/c.py" in paths

  def test_extract_paths_from_tool_calls(self):
    chat = ch.Chat.from_conversation([
      {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
          "id": "call_1",
          "type": "function",
          "function": {
            "name": "write_file",
            "arguments": json.dumps({"file_path": "notes/scratch.txt", "content": "x"}),
          },
        }],
      },
      {"role": "user", "content": "Save notes"},
    ])
    paths = diffscope.extract_response_paths("Updated scratch file.", chat)
    assert "notes/scratch.txt" in paths


class TestViolations:
  def test_find_out_of_scope_against_hinted_paths(self):
    scope = diffscope.UserScope(hinted=["services/boost/src/utils.py"])
    violations = diffscope.find_violations(
      ["services/boost/src/utils.py", "services/boost/src/config.py"],
      scope,
    )
    assert len(violations) == 1
    assert violations[0].path == "services/boost/src/config.py"
    assert violations[0].reason == "out_of_scope"

  def test_find_forbidden_paths(self):
    scope = diffscope.UserScope(
      hinted=["services/boost/src/utils.py"],
      forbidden=["services/boost/src/config.py"],
    )
    violations = diffscope.find_violations(["services/boost/src/config.py"], scope)
    assert len(violations) == 1
    assert violations[0].reason == "forbidden"

  def test_allowed_paths_override_hint_matching(self):
    scope = diffscope.UserScope(allowed=["services/boost/src/utils.py"])
    violations = diffscope.find_violations(["services/boost/src/other.py"], scope)
    assert len(violations) == 1

  def test_path_matches_scope_supports_prefix(self):
    assert diffscope.path_matches_scope(
      "services/boost/src/utils.py",
      ["services/boost/src"],
    )


class TestWorkspaceAndNotes:
  @pytest.mark.asyncio
  async def test_verify_workspace_paths_detects_missing(self):
    with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      target = root / "src" / "exists.py"
      target.parent.mkdir(parents=True)
      target.write_text("ok", encoding="utf-8")

      original = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = str(root)
        missing = await diffscope.verify_workspace_paths([
          "src/exists.py",
          "src/missing.py",
        ])
      finally:
        config.WORKSPACE_ROOT.__value__ = original

    assert missing == ["src/missing.py"]

  def test_build_correction_note_lists_violations_and_scope(self):
    scope = diffscope.UserScope(allowed=["services/boost/src/utils.py"])
    note = diffscope.build_correction_note(
      [diffscope.ScopeViolation("docs/CHANGELOG.md", "out_of_scope")],
      ["src/missing.py"],
      scope,
    )
    assert "OUT_OF_SCOPE: docs/CHANGELOG.md" in note
    assert "MISSING: src/missing.py" in note
    assert "services/boost/src/utils.py" in note


class TestDiffscopeApply:
  @pytest.mark.asyncio
  async def test_apply_passes_through_non_deliverable(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Explain Python dataclasses briefly."},
    ])
    llm = MagicMock()
    llm.stream_final_completion = AsyncMock()

    await diffscope.apply(chat, llm)

    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_apply_passes_through_without_scope_constraints(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement a retry helper with exponential backoff."},
    ])
    llm = MagicMock()
    llm.stream_final_completion = AsyncMock()

    await diffscope.apply(chat, llm)

    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_apply_emits_draft_when_scope_ok(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Only update services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()
    llm.stream_final_completion = AsyncMock(return_value="Changed `services/boost/src/utils.py`.")

    with patch.object(diffscope, "verify_workspace_paths", new=AsyncMock(return_value=[])):
      await diffscope.apply(chat, llm)

    llm.emit_message.assert_awaited_once_with("Changed `services/boost/src/utils.py`.")
    llm.stream_final_completion.assert_awaited_once_with(emit=False)

  @pytest.mark.asyncio
  async def test_apply_revises_once_on_scope_violation(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Only change services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()
    llm.stream_final_completion = AsyncMock(
      return_value="Also edited services/boost/src/config.py for flags.",
    )

    with (
      patch.object(diffscope, "verify_workspace_paths", new=AsyncMock(return_value=[])),
      patch.object(
        diffscope,
        "revise_with_correction",
        new=AsyncMock(return_value="Only updated services/boost/src/utils.py."),
      ) as revise,
    ):
      await diffscope.apply(chat, llm)

    revise.assert_awaited_once()
    llm.emit_message.assert_awaited_once_with("Only updated services/boost/src/utils.py.")

  @pytest.mark.asyncio
  async def test_revise_with_correction_returns_revised_text(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Only touch services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.url = "http://example.com"
    llm.headers = {}
    llm.query_params = {}
    llm.model = "test-model"

    with patch.object(diffscope, "_cheap_llm") as cheap_llm:
      cheap = MagicMock()
      cheap.chat_completion = AsyncMock(return_value="Scoped answer.")
      cheap_llm.return_value = cheap

      revised = await diffscope.revise_with_correction(
        chat,
        llm,
        "Draft touched too many files.",
        "<file_scope_violations></file_scope_violations>",
      )

    assert revised == "Scoped answer."