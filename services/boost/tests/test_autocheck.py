"""Unit tests for the autocheck Boost module."""

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
import deliverable
from modules import autocheck


class TestAutocheckGate:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  def test_needs_autocheck_for_implementation_request(self):
    chat = self._chat("Implement a retry helper in services/boost/src/utils.py")
    assert autocheck.needs_autocheck(chat)
    assert autocheck.autocheck_gate_reason(chat) == "triggered"

  def test_skips_explanatory_question(self):
    chat = self._chat("Explain what asyncio.gather does in plain English.")
    assert not autocheck.needs_autocheck(chat)
    assert autocheck.autocheck_gate_reason(chat) == "not_deliverable"

  def test_skips_research_only_turn(self):
    chat = self._chat(
      "What is the Stripe checkout session API endpoint response format in 2024?"
    )
    assert not autocheck.needs_autocheck(chat)
    assert autocheck.autocheck_gate_reason(chat) == "research_only"

  def test_skips_when_disabled(self):
    chat = self._chat("Implement foo in bar.py")
    original = config.AUTOCHECK_ENABLED.__value__
    try:
      config.AUTOCHECK_ENABLED.__value__ = False
      assert not autocheck.needs_autocheck(chat)
      assert autocheck.autocheck_gate_reason(chat) == "disabled"
    finally:
      config.AUTOCHECK_ENABLED.__value__ = original

  def test_skips_acknowledgments(self):
    assert not autocheck.needs_autocheck(self._chat("thanks!"))
    assert autocheck.autocheck_gate_reason(self._chat("ok")) == "acknowledgment"

  def test_skips_short_messages(self):
    chat = self._chat("fix it")
    assert not autocheck.needs_autocheck(chat)
    assert autocheck.autocheck_gate_reason(chat) == "short_message"

  def test_skips_single_signal_deliverable(self):
    chat = self._chat("Implement a retry helper")
    assert deliverable.count_deliverable_signals(chat) == 1
    assert not autocheck.needs_autocheck(chat)
    assert autocheck.autocheck_gate_reason(chat) == "insufficient_signals"

  def test_triggers_with_two_signals(self):
    chat = self._chat("Implement retry helper in services/boost/src/utils.py")
    assert deliverable.count_deliverable_signals(chat) >= 2
    assert autocheck.needs_autocheck(chat)

  def test_triggers_on_explicit_done_signal_with_prior_coding_context(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
      {"role": "assistant", "content": "Added retry helper with three attempts."},
      {"role": "user", "content": "We're done — ship it."},
    ])
    assert autocheck.needs_autocheck(chat)
    assert autocheck.autocheck_gate_reason(chat) == "triggered"

  def test_triggers_on_looks_good_after_coding_session(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Fix bug in services/boost/src/main.py"},
      {"role": "assistant", "content": "Patched the retry loop in main.py."},
      {"role": "user", "content": "Looks good."},
    ])
    assert autocheck.needs_autocheck(chat)
    assert autocheck.autocheck_gate_reason(chat) == "triggered"

  def test_triggers_on_recent_finish_tool_call(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Add logging to services/boost/src/utils.py"},
      {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
          "id": "call_finish",
          "type": "function",
          "function": {
            "name": "finish",
            "arguments": '{"answer": "Logging added."}',
          },
        }],
      },
      {"role": "tool", "content": "Logging added.", "tool_call_id": "call_finish"},
      {"role": "user", "content": "thanks"},
    ])
    assert autocheck.needs_autocheck(chat)
    assert autocheck.autocheck_gate_reason(chat) == "triggered"

  def test_skips_casual_done_signal_without_coding_context(self):
    chat = self._chat("Ship it")
    assert not autocheck.needs_autocheck(chat)
    assert autocheck.autocheck_gate_reason(chat) == "acknowledgment"

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

  def test_format_audit_status_pass_with_no_findings(self):
    audit = autocheck.AuditResult(verdict="pass", findings=[])
    assert autocheck.format_audit_status(audit) == "Autocheck: pass (0 findings)"

  def test_format_audit_status_revise_with_finding_count(self):
    audit = autocheck.AuditResult(
      verdict="revise",
      findings=[
        autocheck.AuditFinding(severity="major", message="Wrong path"),
        autocheck.AuditFinding(severity="minor", message="Missing test"),
      ],
    )
    assert autocheck.format_audit_status(audit) == "Autocheck: revise (2 findings)"

  def test_format_audit_footer_includes_summary(self):
    audit = autocheck.AuditResult(
      verdict="pass",
      summary="Ready to ship.",
      findings=[],
    )
    footer = autocheck.format_audit_footer(audit)
    assert "Autocheck: pass (0 findings)" in footer
    assert "Ready to ship." in footer

  def test_format_audit_footer_truncates_long_summary(self):
    audit = autocheck.AuditResult(
      verdict="revise",
      summary="x" * 200,
      findings=[autocheck.AuditFinding(severity="major", message="Issue")],
    )
    footer = autocheck.format_audit_footer(audit)
    assert "..." in footer
    assert len(footer.splitlines()[-1]) <= 120

  def test_show_audit_footer_reads_boost_params(self):
    llm = MagicMock()
    llm.boost_params = {"show_audit": "true"}
    assert autocheck.show_audit_footer(llm)

    llm.boost_params = {"show_audit": "false"}
    assert not autocheck.show_audit_footer(llm)

    llm.boost_params = {}
    assert not autocheck.show_audit_footer(llm)

  def test_append_audit_footer_adds_markdown_block(self):
    audit = autocheck.AuditResult(verdict="pass", summary="Ship it", findings=[])
    rendered = autocheck.append_audit_footer("Final answer", audit)
    assert rendered.startswith("Final answer")
    assert "---" in rendered
    assert "Autocheck: pass (0 findings)" in rendered
    assert "Ship it" in rendered


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
  async def test_gather_workspace_context_respects_autocheck_char_limit(self):
    with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      target = root / "src" / "large.py"
      target.parent.mkdir(parents=True)
      target.write_text("x" * 200, encoding="utf-8")

      original_root = config.WORKSPACE_ROOT.__value__
      original_max = config.AUTOCHECK_WORKSPACE_FILE_MAX_CHARS.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = str(root)
        config.AUTOCHECK_WORKSPACE_FILE_MAX_CHARS.__value__ = 50
        context = await autocheck.gather_workspace_context(["src/large.py"])
      finally:
        config.WORKSPACE_ROOT.__value__ = original_root
        config.AUTOCHECK_WORKSPACE_FILE_MAX_CHARS.__value__ = original_max

    assert "truncated to 50 characters" in context

  @pytest.mark.asyncio
  async def test_gather_workspace_context_empty_without_root(self):
    original = config.WORKSPACE_ROOT.__value__
    try:
      config.WORKSPACE_ROOT.__value__ = ""
      context = await autocheck.gather_workspace_context(["src/widget.py"])
    finally:
      config.WORKSPACE_ROOT.__value__ = original
    assert context == ""


class TestWorkspaceEvidence:
  def test_successful_workspace_reads_ignores_errors(self):
    context = (
      '<file path="src/a.py">\nprint(1)\n</file>\n\n'
      '<file path="src/missing.py" error="not found" />'
    )
    reads = autocheck.successful_workspace_reads(context)
    assert reads == ["src/a.py"]

  def test_workspace_evidence_merges_reads_and_tool_calls(self):
    context = '<file path="src/a.py">\nprint(1)\n</file>'
    tool_calls = [{"name": "read_workspace_file", "arguments": {"path": "src/b.py"}}]
    evidence = autocheck.workspace_evidence_paths(context, tool_calls)
    assert evidence == ["src/a.py", "src/b.py"]

  def test_enforce_workspace_evidence_downgrades_pass_without_reads(self):
    audit = autocheck.AuditResult(verdict="pass", summary="Looks good")
    original = config.WORKSPACE_ROOT.__value__
    try:
      config.WORKSPACE_ROOT.__value__ = "/workspace"
      enforced = autocheck.enforce_workspace_evidence(
        audit,
        ["src/main.py"],
        "",
        [],
      )
    finally:
      config.WORKSPACE_ROOT.__value__ = original

    assert enforced.verdict == "revise"
    assert any("workspace file evidence" in finding.message.lower() for finding in enforced.findings)

  def test_enforce_workspace_evidence_allows_pass_with_reads(self):
    audit = autocheck.AuditResult(verdict="pass", summary="Looks good")
    original = config.WORKSPACE_ROOT.__value__
    try:
      config.WORKSPACE_ROOT.__value__ = "/workspace"
      enforced = autocheck.enforce_workspace_evidence(
        audit,
        ["src/main.py"],
        '<file path="src/main.py">\nprint(1)\n</file>',
        [],
      )
    finally:
      config.WORKSPACE_ROOT.__value__ = original

    assert enforced.verdict == "pass"

  def test_enforce_workspace_evidence_allows_pass_with_grep_tool_call(self):
    audit = autocheck.AuditResult(verdict="pass", summary="Looks good")
    original = config.WORKSPACE_ROOT.__value__
    try:
      config.WORKSPACE_ROOT.__value__ = "/workspace"
      enforced = autocheck.enforce_workspace_evidence(
        audit,
        ["src/main.py"],
        "",
        [{
          "name": "grep_workspace",
          "arguments": {"pattern": "retry_helper"},
        }],
      )
    finally:
      config.WORKSPACE_ROOT.__value__ = original

    assert enforced.verdict == "pass"

  def test_workspace_evidence_satisfied_with_grep_context(self):
    context = '<grep pattern="retry_helper" path="src">\nsrc/main.py:10:def retry_helper()\n</grep>'
    assert autocheck.workspace_evidence_satisfied(context, []) is False
    tool_calls = [{
      "name": "grep_workspace",
      "arguments": {"pattern": "retry_helper"},
    }]
    assert autocheck.workspace_evidence_satisfied("", tool_calls) is True

  def test_extract_workspace_tool_calls_from_history(self):
    history = [
      {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
          "id": "call_1",
          "type": "function",
          "function": {
            "name": "read_workspace_file",
            "arguments": '{"path": "src/main.py"}',
          },
        }],
      }
    ]
    calls = autocheck.extract_workspace_tool_calls(history)
    assert len(calls) == 1
    assert calls[0]["arguments"]["path"] == "src/main.py"

  def test_extract_workspace_tool_calls_includes_grep(self):
    history = [
      {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
          "id": "call_2",
          "type": "function",
          "function": {
            "name": "grep_workspace",
            "arguments": '{"pattern": "retry_helper", "glob": "*.py"}',
          },
        }],
      }
    ]
    calls = autocheck.extract_workspace_tool_calls(history)
    assert len(calls) == 1
    assert calls[0]["name"] == "grep_workspace"
    assert calls[0]["arguments"]["pattern"] == "retry_helper"

  def test_enforce_workspace_evidence_allows_pass_with_list_tool_call(self):
    audit = autocheck.AuditResult(verdict="pass", summary="Looks good")
    original = config.WORKSPACE_ROOT.__value__
    try:
      config.WORKSPACE_ROOT.__value__ = "/workspace"
      enforced = autocheck.enforce_workspace_evidence(
        audit,
        ["src/main.py"],
        "",
        [{
          "name": "list_workspace_files",
          "arguments": {"path": "src", "glob": "*.py"},
        }],
      )
    finally:
      config.WORKSPACE_ROOT.__value__ = original

    assert enforced.verdict == "pass"

  def test_workspace_evidence_satisfied_with_list_tool_call(self):
    tool_calls = [{
      "name": "list_workspace_files",
      "arguments": {"path": "src"},
    }]
    assert autocheck.workspace_evidence_satisfied("", tool_calls) is True

  def test_extract_workspace_tool_calls_includes_list(self):
    history = [
      {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
          "id": "call_3",
          "type": "function",
          "function": {
            "name": "list_workspace_files",
            "arguments": '{"path": "src", "glob": "*.py"}',
          },
        }],
      }
    ]
    calls = autocheck.extract_workspace_tool_calls(history)
    assert len(calls) == 1
    assert calls[0]["name"] == "list_workspace_files"
    assert calls[0]["arguments"]["path"] == "src"


class TestSymbolVerification:
  def test_extract_audit_symbols_from_code_blocks(self):
    draft = (
      "Update `retry_helper` in src/utils.py:\n"
      "```python\n"
      "def retry_helper():\n"
      "    pass\n"
      "```"
    )
    symbols = autocheck.extract_audit_symbols(draft)
    assert "retry_helper" in symbols

  @pytest.mark.asyncio
  async def test_verify_symbols_with_grep_finds_matches(self):
    with tempfile.TemporaryDirectory() as workspace:
      target = Path(workspace) / "src" / "utils.py"
      target.parent.mkdir(parents=True)
      target.write_text("def retry_helper():\n    return 3\n", encoding="utf-8")

      original_root = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = workspace
        context = await autocheck.verify_symbols_with_grep(
          ["retry_helper"],
          ["src/utils.py"],
        )
      finally:
        config.WORKSPACE_ROOT.__value__ = original_root

    assert 'pattern="retry_helper"' in context
    assert "retry_helper" in context


class TestMechanicalPreaudit:
  def test_draft_has_code_blocks_detects_fences(self):
    draft = "Use this helper:\n```python\ndef foo():\n    pass\n```"
    assert autocheck.draft_has_code_blocks(draft)
    assert not autocheck.draft_has_code_blocks("No fenced code here.")

  def test_check_code_blocks_without_paths_flags_ungrounded_code(self):
    draft = "Apply this patch:\n```python\nprint(1)\n```"
    findings = autocheck.check_code_blocks_without_paths(draft, [])
    assert len(findings) == 1
    assert "no file paths" in findings[0].message.lower()

  def test_check_code_blocks_without_paths_allows_cited_paths(self):
    draft = "Update src/main.py:\n```python\nprint(1)\n```"
    findings = autocheck.check_code_blocks_without_paths(
      draft,
      ["src/main.py"],
    )
    assert findings == []

  def test_collect_git_diff_context_includes_stat(self):
    with tempfile.TemporaryDirectory() as workspace:
      root = Path(workspace)
      target = root / "src" / "widget.py"
      target.parent.mkdir(parents=True)
      target.write_text("print(1)\n", encoding="utf-8")

      subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
      subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=root,
        check=True,
        capture_output=True,
      )
      subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=root,
        check=True,
        capture_output=True,
      )
      subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
      subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=root,
        check=True,
        capture_output=True,
      )
      target.write_text("print(2)\n", encoding="utf-8")

      original = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = str(root)
        context = autocheck.collect_git_diff_context()
      finally:
        config.WORKSPACE_ROOT.__value__ = original

    assert "<git_diff_stat>" in context
    assert "src/widget.py" in context

  def test_collect_git_diff_context_empty_without_git_repo(self):
    with tempfile.TemporaryDirectory() as workspace:
      original = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = workspace
        context = autocheck.collect_git_diff_context()
      finally:
        config.WORKSPACE_ROOT.__value__ = original

    assert context == ""

  @pytest.mark.asyncio
  async def test_verify_draft_paths_exist_flags_missing_paths(self):
    with tempfile.TemporaryDirectory() as workspace:
      original = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = workspace
        findings = await autocheck.verify_draft_paths_exist(["src/missing.py"])
      finally:
        config.WORKSPACE_ROOT.__value__ = original

    assert len(findings) == 1
    assert "does not exist" in findings[0].message

  @pytest.mark.asyncio
  async def test_verify_draft_paths_exist_allows_existing_paths(self):
    with tempfile.TemporaryDirectory() as workspace:
      target = Path(workspace) / "src" / "main.py"
      target.parent.mkdir(parents=True)
      target.write_text("print(1)\n", encoding="utf-8")

      original = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = workspace
        findings = await autocheck.verify_draft_paths_exist(["src/main.py"])
      finally:
        config.WORKSPACE_ROOT.__value__ = original

    assert findings == []

  @pytest.mark.asyncio
  async def test_run_mechanical_preaudit_flags_code_without_paths(self):
    draft = "Patch:\n```python\nprint(1)\n```"
    git_context, findings = await autocheck.run_mechanical_preaudit(draft, [])
    assert git_context == ""
    assert len(findings) == 1
    assert "code blocks" in findings[0].message.lower()

  @pytest.mark.asyncio
  async def test_run_mechanical_preaudit_flags_missing_paths(self):
    draft = "Update src/missing.py with a helper."
    with tempfile.TemporaryDirectory() as workspace:
      original = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = workspace
        git_context, findings = await autocheck.run_mechanical_preaudit(
          draft,
          ["src/missing.py"],
        )
      finally:
        config.WORKSPACE_ROOT.__value__ = original

    assert git_context == ""
    assert len(findings) == 1
    assert "does not exist" in findings[0].message.lower()

  def test_apply_mechanical_findings_forces_revise(self):
    audit = autocheck.AuditResult(verdict="pass", summary="Looks good", findings=[])
    mechanical = [
      autocheck.AuditFinding(
        severity="major",
        message="Referenced file does not exist in workspace: src/missing.py",
      )
    ]
    merged = autocheck.apply_mechanical_findings(audit, mechanical)
    assert merged.verdict == "revise"
    assert merged.findings[0].message == mechanical[0].message

  def test_enrich_workspace_context_includes_git_and_mechanical_notes(self):
    mechanical = [
      autocheck.AuditFinding(severity="major", message="Missing path"),
    ]
    enriched = autocheck.enrich_workspace_context(
      '<file path="src/a.py">\nprint(1)\n</file>',
      git_diff_context="<git_diff_stat>\nsrc/a.py | 1 +\n</git_diff_stat>",
      mechanical_findings=mechanical,
    )
    assert 'path="src/a.py"' in enriched
    assert "<git_diff_stat>" in enriched
    assert "<mechanical_preaudit>" in enriched
    assert "Missing path" in enriched

  def test_apply_mechanical_findings_keeps_pass_for_warn_only(self):
    audit = autocheck.AuditResult(verdict="pass", summary="Looks good", findings=[])
    warn_only = [
      autocheck.AuditFinding(
        severity="warn",
        message="Consider running tests near changed paths (tests/test_widget.py)",
        fix_hint="Run: pytest tests/test_widget.py",
      )
    ]
    merged = autocheck.apply_mechanical_findings(audit, warn_only)
    assert merged.verdict == "pass"
    assert merged.findings[0].severity == "warn"


class TestTestHint:
  def test_is_test_file_detects_common_patterns(self):
    assert autocheck.is_test_file("tests/test_widget.py")
    assert autocheck.is_test_file("widget_test.py")
    assert autocheck.is_test_file("src/widget.test.ts")
    assert autocheck.is_test_file("src/__tests__/widget.spec.js")
    assert not autocheck.is_test_file("src/widget.py")

  def test_find_nearby_test_files_uses_src_to_tests_swap(self):
    with tempfile.TemporaryDirectory() as workspace:
      root = Path(workspace)
      module = root / "services" / "boost" / "src" / "modules" / "widget.py"
      test_file = root / "services" / "boost" / "tests" / "test_widget.py"
      module.parent.mkdir(parents=True)
      test_file.parent.mkdir(parents=True)
      module.write_text("def widget():\n  return 1\n", encoding="utf-8")
      test_file.write_text("def test_widget():\n  assert True\n", encoding="utf-8")

      found = autocheck.find_nearby_test_files(
        ["services/boost/src/modules/widget.py"],
        root,
      )

    assert found == ["services/boost/tests/test_widget.py"]

  def test_find_nearby_test_files_accepts_direct_test_paths(self):
    with tempfile.TemporaryDirectory() as workspace:
      root = Path(workspace)
      test_file = root / "tests" / "test_widget.py"
      test_file.parent.mkdir(parents=True)
      test_file.write_text("def test_widget():\n  assert True\n", encoding="utf-8")

      found = autocheck.find_nearby_test_files(["tests/test_widget.py"], root)

    assert found == ["tests/test_widget.py"]

  def test_suggest_test_command_from_pyproject_pytest(self):
    with tempfile.TemporaryDirectory() as workspace:
      root = Path(workspace)
      (root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\ntestpaths = [\"tests\"]\n",
        encoding="utf-8",
      )
      command = autocheck.suggest_test_command(
        ["tests/test_widget.py"],
        ["src/widget.py"],
        root,
      )

    assert command == "pytest tests/test_widget.py"

  def test_suggest_test_command_from_package_json_script(self):
    with tempfile.TemporaryDirectory() as workspace:
      root = Path(workspace)
      app_dir = root / "app"
      app_dir.mkdir()
      (app_dir / "package.json").write_text(
        '{"scripts": {"test": "vitest run"}}',
        encoding="utf-8",
      )
      command = autocheck.suggest_test_command(
        ["app/src/widget.test.ts"],
        ["app/src/widget.ts"],
        root,
      )

    assert command == "cd app && npm test"

  def test_suggest_running_tests_emits_warn_finding(self):
    with tempfile.TemporaryDirectory() as workspace:
      root = Path(workspace)
      module = root / "src" / "widget.py"
      test_file = root / "tests" / "test_widget.py"
      module.parent.mkdir(parents=True)
      test_file.parent.mkdir(parents=True)
      module.write_text("def widget():\n  return 1\n", encoding="utf-8")
      test_file.write_text("def test_widget():\n  assert True\n", encoding="utf-8")
      (root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\ntestpaths = [\"tests\"]\n",
        encoding="utf-8",
      )

      original = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = str(root)
        findings = autocheck.suggest_running_tests(["src/widget.py"])
      finally:
        config.WORKSPACE_ROOT.__value__ = original

    assert len(findings) == 1
    assert findings[0].severity == "warn"
    assert "consider running tests" in findings[0].message.lower()
    assert "pytest tests/test_widget.py" in findings[0].fix_hint

  def test_suggest_running_tests_empty_without_workspace(self):
    original = config.WORKSPACE_ROOT.__value__
    try:
      config.WORKSPACE_ROOT.__value__ = ""
      findings = autocheck.suggest_running_tests(["src/widget.py"])
    finally:
      config.WORKSPACE_ROOT.__value__ = original

    assert findings == []

  @pytest.mark.asyncio
  async def test_run_mechanical_preaudit_includes_test_hint(self):
    with tempfile.TemporaryDirectory() as workspace:
      root = Path(workspace)
      module = root / "src" / "widget.py"
      test_file = root / "tests" / "test_widget.py"
      module.parent.mkdir(parents=True)
      test_file.parent.mkdir(parents=True)
      module.write_text("def widget():\n  return 1\n", encoding="utf-8")
      test_file.write_text("def test_widget():\n  assert True\n", encoding="utf-8")
      (root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\ntestpaths = [\"tests\"]\n",
        encoding="utf-8",
      )

      original = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = str(root)
        _git_context, findings = await autocheck.run_mechanical_preaudit(
          "Update src/widget.py with a helper.",
          ["src/widget.py"],
        )
      finally:
        config.WORKSPACE_ROOT.__value__ = original

    assert any(finding.severity == "warn" for finding in findings)
    assert any("consider running tests" in finding.message.lower() for finding in findings)


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

    with patch("research.orchestrate.cheap_llm") as cheap_llm:
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

      audit, debug = await autocheck.run_audit(chat, llm, "draft text")

    assert audit.verdict == "revise"
    assert len(audit.findings) == 1
    assert audit.findings[0].fix_hint == "Use existing module path"
    assert debug.triggered is True
    assert debug.gate_reason == "triggered"
    assert debug.verdict == "revise"

  @pytest.mark.asyncio
  async def test_run_audit_includes_debug_payload(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Fix bug in services/boost/src/main.py"},
    ])
    llm = MagicMock()
    llm.url = "http://example.com"
    llm.headers = {}
    llm.query_params = {}
    llm.model = "test-model"
    original_root = config.WORKSPACE_ROOT.__value__

    try:
      config.WORKSPACE_ROOT.__value__ = "/workspace"
      with patch("research.orchestrate.cheap_llm") as cheap_llm:
        cheap = MagicMock()
        cheap.chat_completion = AsyncMock(
          return_value={"verdict": "pass", "summary": "Ship it", "findings": []},
        )
        cheap_llm.return_value = cheap

        audit, debug = await autocheck.run_audit(
          chat,
          llm,
          "draft text",
          workspace_context='<file path="services/boost/src/main.py">\nprint(1)\n</file>',
          workspace_paths=["services/boost/src/main.py"],
          workspace_tool_calls=[{
            "name": "read_workspace_file",
            "arguments": {"path": "services/boost/src/main.py"},
          }],
        )
    finally:
      config.WORKSPACE_ROOT.__value__ = original_root

    assert audit.verdict == "pass"
    assert debug.triggered is True
    assert debug.gate_reason == "triggered"
    assert debug.tool_calls[0]["arguments"]["path"] == "services/boost/src/main.py"
    assert debug.verdict == "pass"

  @pytest.mark.asyncio
  async def test_run_audit_applies_mechanical_blockers_before_delivery(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Fix bug in services/boost/src/main.py"},
    ])
    llm = MagicMock()
    llm.url = "http://example.com"
    llm.headers = {}
    llm.query_params = {}
    llm.model = "test-model"
    mechanical = [
      autocheck.AuditFinding(
        severity="major",
        message="Draft contains code blocks but cites no file paths",
      )
    ]

    with patch("research.orchestrate.cheap_llm") as cheap_llm:
      cheap = MagicMock()
      cheap.chat_completion = AsyncMock(
        return_value={"verdict": "pass", "summary": "Ship it", "findings": []},
      )
      cheap_llm.return_value = cheap

      audit, debug = await autocheck.run_audit(
        chat,
        llm,
        "```python\nprint(1)\n```",
        mechanical_findings=mechanical,
        git_diff_context="<git_diff_stat>\nsrc/main.py | 1 +\n</git_diff_stat>",
      )

    assert audit.verdict == "revise"
    assert audit.findings[0].message == mechanical[0].message
    assert debug.verdict == "revise"
    prompt_context = cheap.chat_completion.await_args.kwargs["workspace_context"]
    assert "<git_diff_stat>" in prompt_context
    assert "<mechanical_preaudit>" in prompt_context

  @pytest.mark.asyncio
  async def test_run_audit_downgrades_pass_without_workspace_evidence(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Fix bug in services/boost/src/main.py"},
    ])
    llm = MagicMock()
    llm.url = "http://example.com"
    llm.headers = {}
    llm.query_params = {}
    llm.model = "test-model"
    original_root = config.WORKSPACE_ROOT.__value__

    try:
      config.WORKSPACE_ROOT.__value__ = "/workspace"
      with patch("research.orchestrate.cheap_llm") as cheap_llm:
        cheap = MagicMock()
        cheap.chat_completion = AsyncMock(
          return_value={"verdict": "pass", "summary": "Ship it", "findings": []},
        )
        cheap_llm.return_value = cheap

        audit, debug = await autocheck.run_audit(
          chat,
          llm,
          "draft text",
          workspace_paths=["services/boost/src/main.py"],
          workspace_tool_calls=[],
        )
    finally:
      config.WORKSPACE_ROOT.__value__ = original_root

    assert audit.verdict == "revise"
    assert debug.verdict == "revise"

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

    with patch("research.orchestrate.cheap_llm") as cheap_llm:
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
  async def test_apply_defers_final_when_configured(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Explain Python dataclasses briefly."},
    ])
    llm = MagicMock()
    llm.stream_final_completion = AsyncMock()

    with patch.object(autocheck, "generate_draft", new=AsyncMock()) as draft:
      await autocheck.apply(chat, llm, config={"defer_final": True})

    draft.assert_not_called()
    llm.stream_final_completion.assert_not_called()

  @pytest.mark.asyncio
  async def test_apply_runs_mechanical_preaudit_before_llm_audit(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.boost_params = {}
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()
    llm.stream_chat_completion = AsyncMock(return_value="Draft implementation")

    audit = autocheck.AuditResult(verdict="pass", summary="Ship it")
    debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="pass")
    mechanical = [
      autocheck.AuditFinding(severity="major", message="Mechanical blocker"),
    ]

    with (
      patch.object(autocheck, "gather_workspace_context", new=AsyncMock(return_value="")),
      patch.object(
        autocheck,
        "run_mechanical_preaudit",
        new=AsyncMock(return_value=("<git_diff_stat>changed</git_diff_stat>", mechanical)),
      ) as preaudit,
      patch.object(autocheck, "run_audit", new=AsyncMock(return_value=(audit, debug))) as run_audit,
    ):
      await autocheck.apply(chat, llm)

    preaudit.assert_awaited_once()
    assert run_audit.await_args.kwargs["mechanical_findings"] == mechanical
    assert run_audit.await_args.kwargs["git_diff_context"] == "<git_diff_stat>changed</git_diff_stat>"
    status_messages = [call.args[0] for call in llm.emit_status.await_args_list]
    assert "Autocheck: pre-audit checks..." in status_messages

  @pytest.mark.asyncio
  async def test_apply_emits_draft_when_audit_passes(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.boost_params = {}
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()
    llm.stream_chat_completion = AsyncMock(return_value="Draft implementation")

    audit = autocheck.AuditResult(verdict="pass", summary="Ship it")
    debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="pass")

    with (
      patch.object(autocheck, "gather_workspace_context", new=AsyncMock(return_value="")),
      patch.object(autocheck, "run_audit", new=AsyncMock(return_value=(audit, debug))),
      patch.object(autocheck, "revise_draft", new=AsyncMock()) as revise,
    ):
      await autocheck.apply(chat, llm)

    revise.assert_not_called()
    status_messages = [call.args[0] for call in llm.emit_status.await_args_list]
    assert "Autocheck: pass (0 findings)" in status_messages
    llm.emit_message.assert_awaited_once_with("Draft implementation")

  @pytest.mark.asyncio
  async def test_apply_revises_once_when_audit_requests_it(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.boost_params = {}
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()
    llm.stream_chat_completion = AsyncMock(return_value="Draft implementation")

    first_audit = autocheck.AuditResult(
      verdict="revise",
      summary="Fix imports",
      findings=[autocheck.AuditFinding(severity="major", message="Missing import")],
    )
    second_audit = autocheck.AuditResult(verdict="pass", summary="Good now")
    first_debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="revise")
    second_debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="pass")

    with (
      patch.object(autocheck, "gather_workspace_context", new=AsyncMock(return_value="")),
      patch.object(
        autocheck,
        "run_audit",
        new=AsyncMock(side_effect=[(first_audit, first_debug), (second_audit, second_debug)]),
      ),
      patch.object(autocheck, "revise_draft", new=AsyncMock(return_value="Revised implementation")) as revise,
    ):
      await autocheck.apply(chat, llm)

    revise.assert_awaited_once()
    status_messages = [call.args[0] for call in llm.emit_status.await_args_list]
    assert "Autocheck: revise (1 finding)" in status_messages
    assert "Autocheck: pass (0 findings)" in status_messages
    llm.emit_message.assert_awaited_once_with("Revised implementation")

  @pytest.mark.asyncio
  async def test_apply_appends_audit_footer_when_show_audit_enabled(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.boost_params = {"show_audit": "true"}
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()
    llm.stream_chat_completion = AsyncMock(return_value="Draft implementation")

    audit = autocheck.AuditResult(verdict="pass", summary="Ship it")
    debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="pass")

    with (
      patch.object(autocheck, "gather_workspace_context", new=AsyncMock(return_value="")),
      patch.object(autocheck, "run_audit", new=AsyncMock(return_value=(audit, debug))),
    ):
      await autocheck.apply(chat, llm)

    emitted = llm.emit_message.await_args.args[0]
    assert emitted.startswith("Draft implementation")
    assert "Autocheck: pass (0 findings)" in emitted
    assert "Ship it" in emitted

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
          new=AsyncMock(return_value=("- main.py exists", [])),
        ) as explore,
        patch.object(autocheck, "run_audit", new=AsyncMock(return_value=audit)) as run_audit,
      ):
        await autocheck.apply(chat, llm)

      explore.assert_awaited_once()
      assert run_audit.await_args.kwargs["workspace_exploration"] == "- main.py exists"
      assert run_audit.await_args.kwargs["workspace_tool_calls"] == []
    finally:
      config.WORKSPACE_ROOT.__value__ = original_root

  @pytest.mark.asyncio
  async def test_apply_falls_back_on_audit_failure(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.boost_params = {}
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()
    llm.stream_final_completion = AsyncMock()
    llm.stream_chat_completion = AsyncMock(return_value="Draft implementation")

    with (
      patch.object(autocheck, "gather_workspace_context", new=AsyncMock(return_value="")),
      patch.object(autocheck, "run_audit", new=AsyncMock(side_effect=RuntimeError("audit down"))),
    ):
      await autocheck.apply(chat, llm)

    status_messages = [call.args[0] for call in llm.emit_status.await_args_list]
    assert "Autocheck: audit failed — delivering draft" in status_messages
    llm.emit_message.assert_awaited_once_with("Draft implementation")
    llm.stream_final_completion.assert_not_called()