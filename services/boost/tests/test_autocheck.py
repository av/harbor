"""Unit tests for the autocheck Boost module."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chat as ch
import config
import deliverable
from modules import autocheck


class TestAutocheckGate:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  def test_needs_autocheck_for_implementation_request(self):
    chat = self._chat("Implement a retry helper in services/boost/src/utils.py")
    assert autocheck.needs_autocheck(chat)

  def test_skips_explanatory_question(self):
    chat = self._chat("Explain what asyncio.gather does in plain English.")
    assert not autocheck.needs_autocheck(chat)

  def test_skips_when_disabled(self):
    chat = self._chat("Implement foo in bar.py")
    original = config.AUTOCHECK_ENABLED.__value__
    try:
      config.AUTOCHECK_ENABLED.__value__ = False
      assert not autocheck.needs_autocheck(chat)
    finally:
      config.AUTOCHECK_ENABLED.__value__ = original

  def test_should_revise_on_revise_verdict(self):
    audit = autocheck.AuditResult(verdict="revise", summary="Needs work")
    assert autocheck.should_revise(audit)

  def test_should_not_revise_on_pass_verdict(self):
    audit = autocheck.AuditResult(verdict="pass", summary="Looks good")
    assert not autocheck.should_revise(audit)


class TestWorkspacePaths:
  def test_extract_workspace_paths_from_user_and_draft(self):
    user = "Please update services/boost/src/main.py and add tests."
    draft = "Edit `services/boost/src/config.py` for the new flag."
    paths = autocheck.extract_workspace_paths(user, draft)
    assert "services/boost/src/main.py" in paths
    assert "services/boost/src/config.py" in paths

  def test_extract_workspace_paths_respects_limit(self):
    original = config.AUTOCHECK_MAX_WORKSPACE_FILES.__value__
    try:
      config.AUTOCHECK_MAX_WORKSPACE_FILES.__value__ = 1
      user = "Fix a/foo.py and b/bar.py"
      paths = autocheck.extract_workspace_paths(user)
      assert len(paths) == 1
    finally:
      config.AUTOCHECK_MAX_WORKSPACE_FILES.__value__ = original

  def test_format_findings_includes_severity_and_hint(self):
    audit = autocheck.AuditResult(
      verdict="revise",
      findings=[
        autocheck.AuditFinding(
          severity="critical",
          message="Missing import",
          fix_hint="Add `import os`",
        )
      ],
    )
    rendered = autocheck.format_findings(audit)
    assert "[critical] Missing import" in rendered
    assert "Add `import os`" in rendered


class TestWorkspaceContext:
  @pytest.mark.asyncio
  async def test_gather_workspace_context_reads_files(self):
    with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      target = root / "src" / "widget.py"
      target.parent.mkdir(parents=True)
      target.write_text("def widget():\n  return 1\n", encoding="utf-8")

      original = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = str(root)
        context = await autocheck.gather_workspace_context(["src/widget.py"])
      finally:
        config.WORKSPACE_ROOT.__value__ = original

    assert 'path="src/widget.py"' in context
    assert "def widget():" in context

  @pytest.mark.asyncio
  async def test_gather_workspace_context_empty_without_root(self):
    original = config.WORKSPACE_ROOT.__value__
    try:
      config.WORKSPACE_ROOT.__value__ = ""
      context = await autocheck.gather_workspace_context(["src/widget.py"])
    finally:
      config.WORKSPACE_ROOT.__value__ = original
    assert context == ""


class TestAuditAndRevise:
  @pytest.mark.asyncio
  async def test_run_audit_parses_structured_result(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement helper in utils.py"},
    ])
    llm = MagicMock()
    llm.url = "http://example.com"
    llm.headers = {}
    llm.query_params = {}
    llm.model = "test-model"

    with patch.object(autocheck, "_cheap_llm") as cheap_llm:
      cheap = MagicMock()
      cheap.chat_completion = AsyncMock(
        return_value={
          "verdict": "revise",
          "summary": "Path invents a file",
          "findings": [
            {
              "severity": "major",
              "message": "utils.py not present in workspace",
              "fix_hint": "Use existing module path",
            }
          ],
        }
      )
      cheap_llm.return_value = cheap

      audit = await autocheck.run_audit(chat, llm, "draft text")

    assert audit.verdict == "revise"
    assert len(audit.findings) == 1
    assert audit.findings[0].fix_hint == "Use existing module path"

  @pytest.mark.asyncio
  async def test_revise_draft_returns_revised_text(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement helper in utils.py"},
    ])
    llm = MagicMock()
    llm.url = "http://example.com"
    llm.headers = {}
    llm.query_params = {}
    llm.model = "test-model"
    audit = autocheck.AuditResult(
      verdict="revise",
      summary="Fix path",
      findings=[
        autocheck.AuditFinding(
          severity="major",
          message="Wrong file",
          fix_hint="Use services/boost/src/utils.py",
        )
      ],
    )

    with patch.object(autocheck, "_cheap_llm") as cheap_llm:
      cheap = MagicMock()
      cheap.chat_completion = AsyncMock(return_value="Revised answer with correct path.")
      cheap_llm.return_value = cheap

      revised = await autocheck.revise_draft(chat, llm, "Original draft", audit)

    assert revised == "Revised answer with correct path."


class TestAutocheckApply:
  @pytest.mark.asyncio
  async def test_apply_passes_through_non_deliverable(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Explain Python dataclasses briefly."},
    ])
    llm = MagicMock()
    llm.stream_final_completion = AsyncMock()

    with patch.object(autocheck, "generate_draft", new=AsyncMock()) as draft:
      await autocheck.apply(chat, llm)

    draft.assert_not_called()
    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_apply_emits_draft_when_audit_passes(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()
    llm.stream_chat_completion = AsyncMock(return_value="Draft implementation")

    audit = autocheck.AuditResult(verdict="pass", summary="Ship it")

    with (
      patch.object(autocheck, "gather_workspace_context", new=AsyncMock(return_value="")),
      patch.object(autocheck, "run_audit", new=AsyncMock(return_value=audit)),
      patch.object(autocheck, "revise_draft", new=AsyncMock()) as revise,
    ):
      await autocheck.apply(chat, llm)

    revise.assert_not_called()
    llm.emit_message.assert_awaited_once_with("Draft implementation")

  @pytest.mark.asyncio
  async def test_apply_revises_once_when_audit_requests_it(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()
    llm.stream_chat_completion = AsyncMock(return_value="Draft implementation")

    first_audit = autocheck.AuditResult(verdict="revise", summary="Fix imports")
    second_audit = autocheck.AuditResult(verdict="pass", summary="Good now")

    with (
      patch.object(autocheck, "gather_workspace_context", new=AsyncMock(return_value="")),
      patch.object(autocheck, "run_audit", new=AsyncMock(side_effect=[first_audit, second_audit])),
      patch.object(autocheck, "revise_draft", new=AsyncMock(return_value="Revised implementation")) as revise,
    ):
      await autocheck.apply(chat, llm)

    revise.assert_awaited_once()
    llm.emit_message.assert_awaited_once_with("Revised implementation")

  @pytest.mark.asyncio
  async def test_apply_explores_workspace_when_root_configured(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Fix bug in services/boost/src/main.py"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()
    llm.stream_chat_completion = AsyncMock(return_value="Draft with services/boost/src/main.py")

    audit = autocheck.AuditResult(verdict="pass", summary="OK")
    original_root = config.WORKSPACE_ROOT.__value__

    try:
      config.WORKSPACE_ROOT.__value__ = "/workspace"

      with (
        patch.object(autocheck, "gather_workspace_context", new=AsyncMock(return_value="<file />")),
        patch.object(
          autocheck,
          "explore_workspace_with_tools",
          new=AsyncMock(return_value="- main.py exists"),
        ) as explore,
        patch.object(autocheck, "run_audit", new=AsyncMock(return_value=audit)) as run_audit,
      ):
        await autocheck.apply(chat, llm)

      explore.assert_awaited_once()
      assert run_audit.await_args.kwargs["workspace_exploration"] == "- main.py exists"
    finally:
      config.WORKSPACE_ROOT.__value__ = original_root

  @pytest.mark.asyncio
  async def test_apply_falls_back_on_audit_failure(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()
    llm.stream_final_completion = AsyncMock()
    llm.stream_chat_completion = AsyncMock(return_value="Draft implementation")

    with (
      patch.object(autocheck, "gather_workspace_context", new=AsyncMock(return_value="")),
      patch.object(autocheck, "run_audit", new=AsyncMock(side_effect=RuntimeError("audit down"))),
    ):
      await autocheck.apply(chat, llm)

    llm.emit_message.assert_awaited_once_with("Draft implementation")
    llm.stream_final_completion.assert_not_called()