"""Unit tests for the diffscope Boost module."""

import json
import os
import subprocess
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


class TestGitDiffGrounding:
  def test_is_git_workspace_detects_dot_git_directory(self):
    with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      (root / ".git").mkdir()
      assert diffscope.is_git_workspace(root)

  def test_is_git_workspace_false_without_git(self):
    with tempfile.TemporaryDirectory() as tmp:
      assert not diffscope.is_git_workspace(tmp)

  def test_run_git_diff_parses_name_only_and_stat(self):
    with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      (root / ".git").mkdir()

      def fake_run(cmd, **kwargs):
        if cmd == ["git", "diff", "--name-only"]:
          return subprocess.CompletedProcess(cmd, 0, "src/a.py\nsrc/b.py\n", "")
        if cmd == ["git", "diff", "--stat"]:
          return subprocess.CompletedProcess(
            cmd,
            0,
            " src/a.py | 2 +-\n src/b.py | 4 ++++\n 2 files changed, 5 insertions(+), 1 deletion(-)\n",
            "",
          )
        raise AssertionError(f"unexpected git command: {cmd}")

      with patch.object(diffscope.subprocess, "run", side_effect=fake_run):
        result = diffscope.run_git_diff(root)

    assert result is not None
    paths, stat = result
    assert paths == ["src/a.py", "src/b.py"]
    assert "2 files changed" in stat

  def test_run_git_diff_returns_none_on_nonzero_exit(self):
    with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      (root / ".git").mkdir()

      with patch.object(
        diffscope.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(["git", "diff", "--name-only"], 128, "", "fatal"),
      ):
        assert diffscope.run_git_diff(root) is None

  def test_run_git_diff_returns_none_on_timeout(self):
    with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      (root / ".git").mkdir()

      with patch.object(
        diffscope.subprocess,
        "run",
        side_effect=subprocess.TimeoutExpired(cmd=["git", "diff", "--name-only"], timeout=5),
      ):
        assert diffscope.run_git_diff(root) is None

  def test_collect_changed_paths_uses_git_when_available(self):
    with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      (root / ".git").mkdir()
      original = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = str(root)
        with patch.object(
          diffscope,
          "run_git_diff",
          return_value=(["services/boost/src/utils.py"], " utils.py | 1 +"),
        ):
          snapshot = diffscope.collect_changed_paths(
            "Mentioned `services/boost/src/config.py` only.",
          )
      finally:
        config.WORKSPACE_ROOT.__value__ = original

    assert snapshot.mode == "git"
    assert snapshot.paths == [
      "services/boost/src/utils.py",
      "services/boost/src/config.py",
    ]
    assert "utils.py" in snapshot.stat

  def test_collect_changed_paths_merges_draft_paths_when_git_diff_empty(self):
    with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      (root / ".git").mkdir()
      original = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = str(root)
        with patch.object(diffscope, "run_git_diff", return_value=([], "")):
          snapshot = diffscope.collect_changed_paths(
            "Updated services/foo.py and services/bar.py for consistency.",
          )
      finally:
        config.WORKSPACE_ROOT.__value__ = original

    assert snapshot.mode == "git"
    assert snapshot.paths == ["services/foo.py", "services/bar.py"]

  def test_extract_paths_from_write_workspace_file_tool_calls(self):
    chat = ch.Chat.from_conversation([
      {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
          "id": "call_1",
          "type": "function",
          "function": {
            "name": "write_workspace_file",
            "arguments": json.dumps({"file_path": "src/widget.py", "content": "x"}),
          },
        }],
      },
      {"role": "user", "content": "Save widget"},
    ])
    paths = diffscope.extract_response_paths("Saved widget.", chat)
    assert "src/widget.py" in paths

  def test_collect_changed_paths_falls_back_to_heuristic(self):
    text = "Changed `services/boost/src/utils.py`."
    snapshot = diffscope.collect_changed_paths(text)
    assert snapshot.mode == "heuristic"
    assert "services/boost/src/utils.py" in snapshot.paths

  def test_collect_changed_paths_falls_back_when_git_diff_fails(self):
    with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      (root / ".git").mkdir()
      original = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = str(root)
        with patch.object(diffscope, "run_git_diff", return_value=None):
          snapshot = diffscope.collect_changed_paths(
            "Also touched `services/boost/src/config.py`.",
          )
      finally:
        config.WORKSPACE_ROOT.__value__ = original

    assert snapshot.mode == "heuristic"
    assert "services/boost/src/config.py" in snapshot.paths


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

  def test_build_correction_note_includes_git_mode_and_stat(self):
    scope = diffscope.UserScope(allowed=["services/boost/src/utils.py"])
    snapshot = diffscope.ChangedPathsSnapshot(
      paths=["services/boost/src/config.py"],
      stat=" config.py | 2 +",
      mode="git",
    )
    note = diffscope.build_correction_note(
      [diffscope.ScopeViolation("services/boost/src/config.py", "out_of_scope")],
      [],
      scope,
      snapshot,
    )
    assert "Grounding: workspace git diff" in note
    assert "<git_diff_stat>" in note
    assert "config.py | 2 +" in note

  def test_build_revise_scope_sections_lists_allowed_forbidden_and_git_evidence(self):
    scope = diffscope.UserScope(
      allowed=["services/boost/src/utils.py"],
      forbidden=["services/boost/src/config.py"],
    )
    snapshot = diffscope.ChangedPathsSnapshot(
      paths=["services/boost/src/config.py", "docs/CHANGELOG.md"],
      stat=" config.py | 2 +",
      mode="git",
    )
    violations = [
      diffscope.ScopeViolation("services/boost/src/config.py", "out_of_scope"),
      diffscope.ScopeViolation("docs/CHANGELOG.md", "out_of_scope"),
    ]

    sections = diffscope.build_revise_scope_sections(scope, violations, snapshot)

    assert "services/boost/src/utils.py" in sections["allowed_paths"]
    assert "services/boost/src/config.py" in sections["forbidden_paths"]
    assert "confirmed changed in workspace git diff" in sections["out_of_scope_paths"]
    assert "docs/CHANGELOG.md" in sections["out_of_scope_paths"]
    assert "Workspace git diff" in sections["git_evidence"]
    assert "config.py | 2 +" in sections["git_evidence"]


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
    llm.stream_chat_completion = AsyncMock(return_value="Changed `services/boost/src/utils.py`.")

    with patch.object(diffscope, "verify_workspace_paths", new=AsyncMock(return_value=[])):
      await diffscope.apply(chat, llm)

    llm.emit_message.assert_awaited_once_with("Changed `services/boost/src/utils.py`.")
    llm.stream_chat_completion.assert_awaited_once_with(emit=False)

  @pytest.mark.asyncio
  async def test_apply_uses_git_diff_paths_for_scope_check(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Only change services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()
    llm.stream_chat_completion = AsyncMock(
      return_value="Only updated services/boost/src/utils.py in the answer.",
    )
    snapshot = diffscope.ChangedPathsSnapshot(
      paths=["services/boost/src/utils.py", "services/boost/src/config.py"],
      stat=" config.py | 1 +",
      mode="git",
    )

    with (
      patch.object(diffscope, "collect_changed_paths", return_value=snapshot),
      patch.object(diffscope, "verify_workspace_paths", new=AsyncMock(return_value=[])),
      patch.object(
        diffscope,
        "revise_with_correction",
        new=AsyncMock(return_value="Scoped to utils.py only."),
      ) as revise,
    ):
      await diffscope.apply(chat, llm)

    revise.assert_awaited_once()
    llm.emit_message.assert_awaited_once_with("Scoped to utils.py only.")

  @pytest.mark.asyncio
  async def test_apply_revises_once_on_scope_violation(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Only change services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()
    llm.stream_chat_completion = AsyncMock(
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

  @pytest.mark.asyncio
  async def test_revise_with_correction_prompt_includes_explicit_scope_sections(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Only change services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.url = "http://example.com"
    llm.headers = {}
    llm.query_params = {}
    llm.model = "test-model"
    scope = diffscope.UserScope(
      allowed=["services/boost/src/utils.py"],
      forbidden=["services/boost/src/config.py"],
    )
    snapshot = diffscope.ChangedPathsSnapshot(
      paths=["services/boost/src/config.py"],
      stat=" config.py | 1 +",
      mode="git",
    )
    violations = [
      diffscope.ScopeViolation("services/boost/src/config.py", "out_of_scope"),
    ]

    with patch.object(diffscope, "_cheap_llm") as cheap_llm:
      cheap = MagicMock()
      cheap.chat_completion = AsyncMock(return_value="Scoped answer.")
      cheap_llm.return_value = cheap

      await diffscope.revise_with_correction(
        chat,
        llm,
        "Also edited services/boost/src/config.py.",
        "<file_scope_violations></file_scope_violations>",
        scope=scope,
        violations=violations,
        snapshot=snapshot,
      )

    kwargs = cheap.chat_completion.await_args.kwargs
    assert kwargs["prompt"] == diffscope.REVISE_PROMPT
    assert "only revision" in kwargs["prompt"].lower()
    assert "minimal diff" in kwargs["prompt"].lower()
    assert "services/boost/src/utils.py" in kwargs["allowed_paths"]
    assert "services/boost/src/config.py" in kwargs["forbidden_paths"]
    assert "confirmed changed in workspace git diff" in kwargs["out_of_scope_paths"]
    assert "config.py | 1 +" in kwargs["git_evidence"]