"""Regression tests for diffscope git + draft path merging."""

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


class TestDiffscopeGitDraftMerge:
  def test_empty_git_diff_still_flags_out_of_scope_draft_paths(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Only change services/foo.py"},
    ])
    scope = diffscope.extract_user_scope(chat)
    draft = "Updated services/foo.py and also services/bar.py for consistency."

    with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      (root / ".git").mkdir()
      original = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = str(root)
        with patch.object(diffscope, "run_git_diff", return_value=([], "")):
          snapshot = diffscope.collect_changed_paths(draft, chat)
      finally:
        config.WORKSPACE_ROOT.__value__ = original

    violations = diffscope.find_violations(snapshot.paths, scope)
    assert snapshot.mode == "git"
    assert any(v.path == "services/bar.py" and v.reason == "out_of_scope" for v in violations)

  @pytest.mark.asyncio
  async def test_apply_revises_when_git_diff_empty_but_draft_violates_scope(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Only change services/foo.py"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()
    llm.stream_final_completion = AsyncMock(
      return_value="Updated services/foo.py and services/bar.py for consistency.",
    )

    with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      (root / ".git").mkdir()
      original = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = str(root)
        with (
          patch.object(diffscope, "run_git_diff", return_value=([], "")),
          patch.object(diffscope, "verify_workspace_paths", new=AsyncMock(return_value=[])),
          patch.object(
            diffscope,
            "revise_with_correction",
            new=AsyncMock(return_value="Only updated services/foo.py."),
          ) as revise,
        ):
          await diffscope.apply(chat, llm)
      finally:
        config.WORKSPACE_ROOT.__value__ = original

    revise.assert_awaited_once()
    llm.emit_message.assert_awaited_once_with("Only updated services/foo.py.")