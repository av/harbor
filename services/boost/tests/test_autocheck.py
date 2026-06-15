"""Unit tests for the autocheck Boost module."""

import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chat as ch
import config
import deliverable
import tools.registry as tool_registry
from modules import autocheck, tools
from state import request as request_state
from helpers import mock_autocheck_cheap_llm


def _patch_autocheck_draft_llm(
    draft_response: str = "Draft implementation",
    *,
    draft_side_effect=None,
):
    cheap = mock_autocheck_cheap_llm(
        draft_response=draft_response,
        draft_side_effect=draft_side_effect,
    )
    return patch("research.orchestrate.cheap_llm", return_value=cheap)


@contextmanager
def request_context():
  req = MagicMock()
  req.state = type("State", (), {})()
  token_req = request_state.set(req)
  try:
    yield req
  finally:
    request_state.reset(token_req)
    if hasattr(req.state, "local_tools"):
      delattr(req.state, "local_tools")


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

  @pytest.mark.parametrize(
    "conversation,expected_needs_autocheck,expected_gate_reason,expected_signal_count",
    [
      pytest.param(
        [{"role": "user", "content": "The retry loop is broken and users cannot sign in"}],
        False,
        "insufficient_signals",
        0,
        id="zero_signals_skip",
      ),
      pytest.param(
        [{"role": "user", "content": "Implement a retry helper"}],
        False,
        "insufficient_signals",
        1,
        id="one_signal_skip",
      ),
      pytest.param(
        [{"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"}],
        True,
        "triggered",
        2,
        id="two_signals_trigger",
      ),
      pytest.param(
        [
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
        ],
        True,
        "triggered",
        None,
        id="finish_tool_triggers",
      ),
      pytest.param(
        [
          {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
          {"role": "assistant", "content": "Added retry helper with three attempts."},
          {"role": "user", "content": "We're done — ship it."},
        ],
        True,
        "triggered",
        None,
        id="explicit_done_triggers",
      ),
    ],
  )
  def test_deliverable_gate(
    self,
    conversation,
    expected_needs_autocheck,
    expected_gate_reason,
    expected_signal_count,
  ):
    chat = ch.Chat.from_conversation(conversation)
    if expected_signal_count is not None:
      assert deliverable.count_deliverable_signals(chat) == expected_signal_count
    assert autocheck.needs_autocheck(chat) == expected_needs_autocheck
    assert autocheck.autocheck_gate_reason(chat) == expected_gate_reason

  def test_triggers_on_looks_good_after_coding_session(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Fix bug in services/boost/src/main.py"},
      {"role": "assistant", "content": "Patched the retry loop in main.py."},
      {"role": "user", "content": "Looks good."},
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

  def test_clamp_max_revise_passes_caps_at_two(self):
    assert autocheck.clamp_max_revise_passes(0) == 0
    assert autocheck.clamp_max_revise_passes(1) == 1
    assert autocheck.clamp_max_revise_passes(2) == 2
    assert autocheck.clamp_max_revise_passes(5) == 2

  def test_effective_max_revise_passes_defaults_to_one(self):
    original_revise = config.AUTOCHECK_MAX_REVISE_PASSES.__value__
    original_strict = config.AUTOCHECK_STRICT.__value__
    try:
      config.AUTOCHECK_MAX_REVISE_PASSES.__value__ = 1
      config.AUTOCHECK_STRICT.__value__ = False
      assert autocheck.effective_max_revise_passes() == 1
    finally:
      config.AUTOCHECK_MAX_REVISE_PASSES.__value__ = original_revise
      config.AUTOCHECK_STRICT.__value__ = original_strict

  def test_effective_max_revise_passes_adds_one_in_strict_mode(self):
    original_revise = config.AUTOCHECK_MAX_REVISE_PASSES.__value__
    original_strict = config.AUTOCHECK_STRICT.__value__
    try:
      config.AUTOCHECK_MAX_REVISE_PASSES.__value__ = 1
      config.AUTOCHECK_STRICT.__value__ = True
      assert autocheck.effective_max_revise_passes() == 2
    finally:
      config.AUTOCHECK_MAX_REVISE_PASSES.__value__ = original_revise
      config.AUTOCHECK_STRICT.__value__ = original_strict

  def test_effective_max_revise_passes_stays_capped_when_strict_and_config_two(self):
    original_revise = config.AUTOCHECK_MAX_REVISE_PASSES.__value__
    original_strict = config.AUTOCHECK_STRICT.__value__
    try:
      config.AUTOCHECK_MAX_REVISE_PASSES.__value__ = 2
      config.AUTOCHECK_STRICT.__value__ = True
      assert autocheck.effective_max_revise_passes() == 2
    finally:
      config.AUTOCHECK_MAX_REVISE_PASSES.__value__ = original_revise
      config.AUTOCHECK_STRICT.__value__ = original_strict

  def test_strict_mode_requires_workspace_root_gate_reason(self):
    chat = self._chat("Implement retry helper in services/boost/src/utils.py")
    original_strict = config.AUTOCHECK_STRICT.__value__
    original_root = config.WORKSPACE_ROOT.__value__
    try:
      config.AUTOCHECK_STRICT.__value__ = True
      config.WORKSPACE_ROOT.__value__ = ""
      assert autocheck.autocheck_gate_reason(chat) == "workspace_unconfigured"
      assert not autocheck.needs_autocheck(chat)

      config.WORKSPACE_ROOT.__value__ = "/workspace"
      assert autocheck.autocheck_gate_reason(chat) == "triggered"
      assert autocheck.needs_autocheck(chat)
    finally:
      config.AUTOCHECK_STRICT.__value__ = original_strict
      config.WORKSPACE_ROOT.__value__ = original_root

  def test_non_strict_mode_allows_missing_workspace_root(self):
    chat = self._chat("Implement retry helper in services/boost/src/utils.py")
    original_strict = config.AUTOCHECK_STRICT.__value__
    original_root = config.WORKSPACE_ROOT.__value__
    try:
      config.AUTOCHECK_STRICT.__value__ = False
      config.WORKSPACE_ROOT.__value__ = ""
      assert autocheck.autocheck_gate_reason(chat) == "triggered"
      assert autocheck.needs_autocheck(chat)
    finally:
      config.AUTOCHECK_STRICT.__value__ = original_strict
      config.WORKSPACE_ROOT.__value__ = original_root


class TestNormalizeRepoPath:
  def test_strips_dot_slash_prefix(self):
    assert deliverable.normalize_repo_path("./services/foo.py") == "services/foo.py"
    assert deliverable.normalize_repo_path(" ./services/foo.py") == "services/foo.py"
    assert deliverable.normalize_repo_path("././services/foo.py") == "services/foo.py"

  def test_strips_wrapping_backticks(self):
    assert deliverable.normalize_repo_path("`services/foo.py`") == "services/foo.py"
    assert deliverable.normalize_repo_path("`./services/foo.py`") == "services/foo.py"

  def test_strips_wrapping_quotes_and_parens(self):
    assert deliverable.normalize_repo_path("'./services/foo.py'") == "services/foo.py"
    assert deliverable.normalize_repo_path("(./services/foo.py)") == "services/foo.py"

  def test_preserves_parent_relative_paths(self):
    assert deliverable.normalize_repo_path("../outside/foo.py") == "../outside/foo.py"


class TestWorkspacePaths:
  def test_extract_workspace_paths_from_user_and_draft(self):
    user = "Please update services/boost/src/main.py and add tests."
    draft = "Edit `services/boost/src/config.py` for the new flag."
    paths = autocheck.extract_workspace_paths(user, draft)
    assert "services/boost/src/main.py" in paths
    assert "services/boost/src/config.py" in paths

  def test_extract_workspace_paths_normalizes_dot_slash_prefix(self):
    user = "Fix ./services/boost/src/main.py and ./services/boost/src/utils.py"
    paths = autocheck.extract_workspace_paths(user)
    assert paths == [
      "services/boost/src/main.py",
      "services/boost/src/utils.py",
    ]

  def test_extract_workspace_paths_normalizes_backtick_dot_slash(self):
    draft = "Edit `./services/boost/src/config.py` and `./services/boost/src/main.py`"
    paths = autocheck.extract_workspace_paths(draft)
    assert paths == [
      "services/boost/src/config.py",
      "services/boost/src/main.py",
    ]

  def test_extract_workspace_paths_dedupes_equivalent_paths(self):
    user = "Update services/boost/src/main.py"
    draft = "Also touch `./services/boost/src/main.py`"
    paths = autocheck.extract_workspace_paths(user, draft)
    assert paths == ["services/boost/src/main.py"]

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

  def test_format_skipped_status_includes_gate_reason(self):
    assert autocheck.format_skipped_status("not_deliverable") == (
      "Autocheck: skipped (not_deliverable)"
    )
    assert autocheck.format_skipped_status("acknowledgment") == (
      "Autocheck: skipped (acknowledgment)"
    )
    assert autocheck.format_skipped_status("draft_generation_failed") == (
      "Autocheck: skipped (draft_generation_failed)"
    )
    assert autocheck.format_skipped_status("audit_failed") == (
      "Autocheck: skipped (audit_failed)"
    )
    assert autocheck.format_skipped_status("workspace_unconfigured") == (
      "Autocheck: skipped (workspace_unconfigured)"
    )

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
    original = config.AUTOCHECK_SHOW_AUDIT.__value__
    try:
      config.AUTOCHECK_SHOW_AUDIT.__value__ = False
      assert not autocheck.show_audit_footer(llm)

      config.AUTOCHECK_SHOW_AUDIT.__value__ = True
      assert autocheck.show_audit_footer(llm)
    finally:
      config.AUTOCHECK_SHOW_AUDIT.__value__ = original

  def test_show_audit_footer_boost_param_overrides_config(self):
    llm = MagicMock()
    original = config.AUTOCHECK_SHOW_AUDIT.__value__
    try:
      config.AUTOCHECK_SHOW_AUDIT.__value__ = True
      llm.boost_params = {"show_audit": "false"}
      assert not autocheck.show_audit_footer(llm)

      config.AUTOCHECK_SHOW_AUDIT.__value__ = False
      llm.boost_params = {"show_audit": "true"}
      assert autocheck.show_audit_footer(llm)
    finally:
      config.AUTOCHECK_SHOW_AUDIT.__value__ = original

  def test_append_audit_footer_adds_markdown_block(self):
    audit = autocheck.AuditResult(verdict="pass", summary="Ship it", findings=[])
    rendered = autocheck.append_audit_footer("Final answer", audit)
    assert rendered.startswith("Final answer")
    assert "---" in rendered
    assert "Autocheck: pass (0 findings)" in rendered
    assert "Ship it" in rendered

  def test_blocking_findings_returns_critical_and_major_only(self):
    audit = autocheck.AuditResult(
      verdict="revise",
      findings=[
        autocheck.AuditFinding(severity="critical", message="Broken import"),
        autocheck.AuditFinding(severity="major", message="Wrong path"),
        autocheck.AuditFinding(severity="minor", message="Style nit"),
        autocheck.AuditFinding(severity="warn", message="Run tests"),
      ],
    )
    blockers = autocheck.blocking_findings(audit)
    assert len(blockers) == 2
    assert {finding.severity for finding in blockers} == {"critical", "major"}

  def test_should_prepend_strict_warning_when_enabled_with_blockers(self):
    audit = autocheck.AuditResult(
      verdict="revise",
      findings=[autocheck.AuditFinding(severity="major", message="Wrong path")],
    )
    original = config.AUTOCHECK_STRICT.__value__
    try:
      config.AUTOCHECK_STRICT.__value__ = True
      assert autocheck.should_prepend_strict_warning(audit)
      config.AUTOCHECK_STRICT.__value__ = False
      assert not autocheck.should_prepend_strict_warning(audit)
    finally:
      config.AUTOCHECK_STRICT.__value__ = original

  def test_should_not_prepend_strict_warning_for_warn_only_findings(self):
    audit = autocheck.AuditResult(
      verdict="pass",
      findings=[
        autocheck.AuditFinding(
          severity="warn",
          message="Consider running tests",
          fix_hint="pytest tests/test_widget.py",
        ),
      ],
    )
    original = config.AUTOCHECK_STRICT.__value__
    try:
      config.AUTOCHECK_STRICT.__value__ = True
      assert not autocheck.should_prepend_strict_warning(audit)
    finally:
      config.AUTOCHECK_STRICT.__value__ = original

  def test_format_strict_warning_banner_lists_blockers(self):
    audit = autocheck.AuditResult(
      verdict="revise",
      summary="Fix imports before shipping.",
      findings=[
        autocheck.AuditFinding(
          severity="major",
          message="Missing import",
          fix_hint="Add `import os`",
        ),
        autocheck.AuditFinding(severity="warn", message="Run tests"),
      ],
    )
    banner = autocheck.format_strict_warning_banner(audit)
    assert "Autocheck warning" in banner
    assert "Fix imports before shipping." in banner
    assert "[major] Missing import" in banner
    assert "Add `import os`" in banner
    assert "[warn]" not in banner

  def test_prepend_strict_warning_banner_adds_blockquote_before_answer(self):
    audit = autocheck.AuditResult(
      verdict="revise",
      findings=[autocheck.AuditFinding(severity="major", message="Wrong path")],
    )
    rendered = autocheck.prepend_strict_warning_banner("Final answer", audit)
    assert rendered.startswith("> **Autocheck warning:**")
    assert rendered.endswith("Final answer")

  def test_format_audit_artifact_html_renders_findings_table(self):
    audit = autocheck.AuditResult(
      verdict="revise",
      summary="Fix imports before shipping.",
      findings=[
        autocheck.AuditFinding(
          severity="major",
          message='Missing import in `utils.py`',
          fix_hint="Add `import os`",
        ),
        autocheck.AuditFinding(
          severity="warn",
          message="Consider running tests",
          fix_hint="",
        ),
      ],
    )
    rendered = autocheck.format_audit_artifact_html(audit)
    assert "<table>" in rendered
    assert "Fix imports before shipping." in rendered
    assert "Missing import in" in rendered
    assert "Add `import os`" in rendered
    assert "verdict-revise" in rendered
    assert "<td>—</td>" in rendered

  def test_format_audit_artifact_html_escapes_markup(self):
    audit = autocheck.AuditResult(
      verdict="pass",
      summary="<script>alert(1)</script>",
      findings=[
        autocheck.AuditFinding(
          severity="info",
          message="<b>not bold</b>",
          fix_hint='Use "quotes"',
        ),
      ],
    )
    rendered = autocheck.format_audit_artifact_html(audit)
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "&lt;b&gt;not bold&lt;/b&gt;" in rendered

  def test_format_audit_artifact_html_shows_empty_findings_row(self):
    audit = autocheck.AuditResult(verdict="pass", findings=[])
    rendered = autocheck.format_audit_artifact_html(audit)
    assert "No findings." in rendered


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


class TestWorkspaceExploration:
  @pytest.mark.asyncio
  async def test_explore_workspace_with_tools_calls_read_and_grep_for_draft_paths(self):
    draft = (
      "Update `services/boost/src/main.py` and verify `retry_helper` exists."
    )
    paths = ["services/boost/src/main.py"]

    with tempfile.TemporaryDirectory() as workspace:
      original_root = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = workspace
        chat = ch.Chat.from_conversation([
          {"role": "user", "content": "Fix retry in services/boost/src/main.py"},
        ])
        llm = MagicMock()
        llm.chat = chat

        mock_read = AsyncMock(return_value="def retry_helper():\n  pass\n")
        mock_grep = AsyncMock(
          return_value="services/boost/src/main.py:10:def retry_helper()\n",
        )

        async def simulate_exploration(**kwargs):
          read_tool = tool_registry.get_local_tool("read_workspace_file")
          grep_tool = tool_registry.get_local_tool("grep_workspace")
          await read_tool("services/boost/src/main.py")
          await grep_tool("retry_helper", glob="*.py")

          chat.tool_call({
            "id": "call_read",
            "type": "function",
            "function": {
              "name": "read_workspace_file",
              "arguments": '{"path": "services/boost/src/main.py"}',
            },
          })
          chat.tool("call_read", "def retry_helper():\n  pass\n")
          chat.tool_call({
            "id": "call_grep",
            "type": "function",
            "function": {
              "name": "grep_workspace",
              "arguments": '{"pattern": "retry_helper", "glob": "*.py"}',
            },
          })
          chat.tool("call_grep", "services/boost/src/main.py:10:def retry_helper()\n")
          chat.assistant("- services/boost/src/main.py contains retry_helper")
          return "- services/boost/src/main.py contains retry_helper"

        llm.stream_chat_completion = AsyncMock(side_effect=simulate_exploration)

        with (
          request_context(),
          patch("modules.tools.read_workspace_file", mock_read),
          patch("modules.tools.grep_workspace", mock_grep),
        ):
          notes, tool_calls = await autocheck.explore_workspace_with_tools(
            llm,
            draft,
            paths,
          )

        mock_read.assert_awaited_once_with("services/boost/src/main.py")
        mock_grep.assert_awaited_once_with("retry_helper", glob="*.py")
        assert "retry_helper" in notes
        assert len(tool_calls) == 2
        assert tool_calls[0]["name"] == "read_workspace_file"
        assert tool_calls[0]["arguments"]["path"] == "services/boost/src/main.py"
        assert tool_calls[1]["name"] == "grep_workspace"
        assert tool_calls[1]["arguments"]["pattern"] == "retry_helper"

        explore_kwargs = llm.stream_chat_completion.await_args.kwargs
        assert explore_kwargs["prompt"] == autocheck.WORKSPACE_EXPLORE_PROMPT
        assert "services/boost/src/main.py" in explore_kwargs["paths"]
        assert explore_kwargs["draft_excerpt"] == draft[:4000]
        assert explore_kwargs["emit"] is False
      finally:
        config.WORKSPACE_ROOT.__value__ = original_root


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

  def test_workspace_evidence_normalizes_dot_slash_tool_paths(self):
    context = '<file path="./src/a.py">\nprint(1)\n</file>'
    tool_calls = [{"name": "read_workspace_file", "arguments": {"path": "./src/b.py"}}]
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

  def test_workspace_evidence_satisfied_with_git_diff_tool_call(self):
    tool_calls = [{
      "name": "git_diff_workspace",
      "arguments": {"path": "."},
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

  @pytest.mark.asyncio
  async def test_collect_git_diff_context_includes_stat(self):
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
        context = await autocheck.collect_git_diff_context()
      finally:
        config.WORKSPACE_ROOT.__value__ = original

    assert "<git_diff_stat>" in context
    assert "<git_diff_name_only>" in context
    assert "src/widget.py" in context

  @pytest.mark.asyncio
  async def test_collect_git_diff_context_empty_without_git_repo(self):
    with tempfile.TemporaryDirectory() as workspace:
      original = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = workspace
        context = await autocheck.collect_git_diff_context()
      finally:
        config.WORKSPACE_ROOT.__value__ = original

    assert context == ""

  @pytest.mark.asyncio
  async def test_run_mechanical_preaudit_uses_git_diff_workspace_when_repo_mocked_as_git(
    self,
  ):
    with tempfile.TemporaryDirectory() as workspace:
      root = Path(workspace)
      (root / ".git").mkdir()
      target = root / "src" / "widget.py"
      target.parent.mkdir(parents=True)
      target.write_text("print(2)\n", encoding="utf-8")

      def fake_run(cmd, **kwargs):
        if cmd[:3] == ["git", "diff", "--name-only"]:
          return subprocess.CompletedProcess(cmd, 0, "src/widget.py\n", "")
        if cmd[:3] == ["git", "diff", "--stat"]:
          return subprocess.CompletedProcess(
            cmd,
            0,
            " src/widget.py | 1 +\n 1 file changed, 1 insertion(+), 1 deletion(-)\n",
            "",
          )
        raise AssertionError(f"unexpected git command: {cmd}")

      original = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = str(root)
        with patch("modules.diffscope.subprocess.run", side_effect=fake_run):
          with patch(
            "modules.tools.git_diff_workspace",
            wraps=tools.git_diff_workspace,
          ) as git_diff_workspace:
            git_context, findings = await autocheck.run_mechanical_preaudit(
              "Update src/widget.py with a helper.",
              ["src/widget.py"],
            )
      finally:
        config.WORKSPACE_ROOT.__value__ = original

    git_diff_workspace.assert_awaited_once()
    assert "<git_diff_stat>" in git_context
    assert "<git_diff_name_only>" in git_context
    assert "src/widget.py" in git_context
    assert findings == []

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


class TestLinterHint:
  def test_has_eslint_config_detects_common_files(self):
    with tempfile.TemporaryDirectory() as workspace:
      root = Path(workspace)
      (root / ".eslintrc").write_text("{}", encoding="utf-8")
      assert autocheck._has_eslint_config(root)

      (root / ".eslintrc").unlink()
      (root / ".eslintrc.json").write_text("{}", encoding="utf-8")
      assert autocheck._has_eslint_config(root)

  def test_detect_linter_at_directory_finds_ruff_toml(self):
    with tempfile.TemporaryDirectory() as workspace:
      root = Path(workspace)
      (root / "ruff.toml").write_text("[lint]\n", encoding="utf-8")
      assert autocheck._detect_linter_at_directory(root) == "ruff"

  def test_detect_linter_at_directory_finds_pyproject_ruff(self):
    with tempfile.TemporaryDirectory() as workspace:
      root = Path(workspace)
      (root / "pyproject.toml").write_text(
        "[tool.ruff]\nline-length = 88\n",
        encoding="utf-8",
      )
      assert autocheck._detect_linter_at_directory(root) == "ruff"

  def test_discover_nearby_linters_walks_up_from_changed_paths(self):
    with tempfile.TemporaryDirectory() as workspace:
      root = Path(workspace)
      app_dir = root / "app" / "src"
      app_dir.mkdir(parents=True)
      (root / "app" / ".eslintrc").write_text("{}", encoding="utf-8")

      found = autocheck.discover_nearby_linters(["app/src/widget.ts"], root)

    assert found == [("eslint", root / "app")]

  def test_suggest_lint_command_for_eslint_and_ruff(self):
    with tempfile.TemporaryDirectory() as workspace:
      root = Path(workspace)
      (root / ".eslintrc").write_text("{}", encoding="utf-8")
      (root / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")
      command = autocheck.suggest_lint_command(
        [("eslint", root), ("ruff", root)],
        ["src/widget.ts", "src/widget.py"],
        root,
      )

    assert "npx eslint src/widget.ts" in command
    assert "ruff check src/widget.py" in command

  def test_suggest_lint_command_uses_subdirectory_prefix(self):
    with tempfile.TemporaryDirectory() as workspace:
      root = Path(workspace)
      app_dir = root / "app"
      app_dir.mkdir()
      (app_dir / "ruff.toml").write_text("[lint]\n", encoding="utf-8")
      command = autocheck.suggest_lint_command(
        [("ruff", app_dir)],
        ["app/src/widget.py"],
        root,
      )

    assert command == "cd app && ruff check app/src/widget.py"

  def test_suggest_running_linter_emits_warn_finding(self):
    with tempfile.TemporaryDirectory() as workspace:
      root = Path(workspace)
      target = root / "src" / "widget.py"
      target.parent.mkdir(parents=True)
      target.write_text("def widget():\n  return 1\n", encoding="utf-8")
      (root / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")

      original = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = str(root)
        findings = autocheck.suggest_running_linter(["src/widget.py"])
      finally:
        config.WORKSPACE_ROOT.__value__ = original

    assert len(findings) == 1
    assert findings[0].severity == "warn"
    assert "consider running the linter" in findings[0].message.lower()
    assert "ruff check src/widget.py" in findings[0].fix_hint

  def test_suggest_running_linter_skips_without_eligible_extensions(self):
    with tempfile.TemporaryDirectory() as workspace:
      root = Path(workspace)
      (root / ".eslintrc").write_text("{}", encoding="utf-8")

      original = config.WORKSPACE_ROOT.__value__
      try:
        config.WORKSPACE_ROOT.__value__ = str(root)
        findings = autocheck.suggest_running_linter(["src/widget.py"])
      finally:
        config.WORKSPACE_ROOT.__value__ = original

    assert findings == []

  def test_suggest_running_linter_empty_without_workspace(self):
    original = config.WORKSPACE_ROOT.__value__
    try:
      config.WORKSPACE_ROOT.__value__ = ""
      findings = autocheck.suggest_running_linter(["src/widget.py"])
    finally:
      config.WORKSPACE_ROOT.__value__ = original

    assert findings == []

  @pytest.mark.asyncio
  async def test_run_mechanical_preaudit_includes_linter_hint(self):
    with tempfile.TemporaryDirectory() as workspace:
      root = Path(workspace)
      target = root / "src" / "widget.py"
      target.parent.mkdir(parents=True)
      target.write_text("def widget():\n  return 1\n", encoding="utf-8")
      (root / "ruff.toml").write_text("[lint]\n", encoding="utf-8")

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
    assert any("consider running the linter" in finding.message.lower() for finding in findings)


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

  def test_audit_llm_keeps_request_model_when_unset(self):
    llm = MagicMock()
    llm.model = "request-model"
    cheap = MagicMock()
    cheap.model = "request-model"
    original = config.AUTOCHECK_AUDIT_MODEL.__value__

    try:
      config.AUTOCHECK_AUDIT_MODEL.__value__ = ""
      with patch("research.orchestrate.cheap_llm", return_value=cheap) as cheap_llm:
        result = autocheck.audit_llm(llm)
    finally:
      config.AUTOCHECK_AUDIT_MODEL.__value__ = original

    cheap_llm.assert_called_once_with(llm)
    assert result is cheap
    assert result.model == "request-model"

  def test_audit_llm_overrides_model_when_configured(self):
    llm = MagicMock()
    llm.model = "request-model"
    cheap = MagicMock()
    cheap.model = "request-model"
    original = config.AUTOCHECK_AUDIT_MODEL.__value__

    try:
      config.AUTOCHECK_AUDIT_MODEL.__value__ = "  gpt-4o-mini  "
      with patch("research.orchestrate.cheap_llm", return_value=cheap):
        result = autocheck.audit_llm(llm)
    finally:
      config.AUTOCHECK_AUDIT_MODEL.__value__ = original

    assert result.model == "gpt-4o-mini"

  def test_draft_llm_keeps_request_model_when_unset(self):
    llm = MagicMock()
    llm.model = "request-model"
    cheap = MagicMock()
    cheap.model = "request-model"
    original = config.AUTOCHECK_DRAFT_MODEL.__value__

    try:
      config.AUTOCHECK_DRAFT_MODEL.__value__ = ""
      with patch("research.orchestrate.cheap_llm", return_value=cheap) as cheap_llm:
        result = autocheck.draft_llm(llm)
    finally:
      config.AUTOCHECK_DRAFT_MODEL.__value__ = original

    cheap_llm.assert_called_once_with(llm)
    assert result is cheap
    assert result.model == "request-model"

  def test_draft_llm_overrides_model_when_configured(self):
    llm = MagicMock()
    llm.model = "request-model"
    cheap = MagicMock()
    cheap.model = "request-model"
    original = config.AUTOCHECK_DRAFT_MODEL.__value__

    try:
      config.AUTOCHECK_DRAFT_MODEL.__value__ = "  gpt-4o  "
      with patch("research.orchestrate.cheap_llm", return_value=cheap):
        result = autocheck.draft_llm(llm)
    finally:
      config.AUTOCHECK_DRAFT_MODEL.__value__ = original

    assert result.model == "gpt-4o"

  def test_revise_llm_keeps_request_model_when_unset(self):
    llm = MagicMock()
    llm.model = "request-model"
    cheap = MagicMock()
    cheap.model = "request-model"
    original = config.AUTOCHECK_REVISE_MODEL.__value__

    try:
      config.AUTOCHECK_REVISE_MODEL.__value__ = ""
      with patch("research.orchestrate.cheap_llm", return_value=cheap) as cheap_llm:
        result = autocheck.revise_llm(llm)
    finally:
      config.AUTOCHECK_REVISE_MODEL.__value__ = original

    cheap_llm.assert_called_once_with(llm)
    assert result is cheap
    assert result.model == "request-model"

  def test_revise_llm_overrides_model_when_configured(self):
    llm = MagicMock()
    llm.model = "request-model"
    cheap = MagicMock()
    cheap.model = "request-model"
    original = config.AUTOCHECK_REVISE_MODEL.__value__

    try:
      config.AUTOCHECK_REVISE_MODEL.__value__ = "  gpt-4o  "
      with patch("research.orchestrate.cheap_llm", return_value=cheap):
        result = autocheck.revise_llm(llm)
    finally:
      config.AUTOCHECK_REVISE_MODEL.__value__ = original

    assert result.model == "gpt-4o"

  @pytest.mark.asyncio
  async def test_generate_draft_uses_draft_model_override(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement helper in utils.py"},
    ])
    llm = MagicMock()
    llm.model = "request-model"
    cheap = MagicMock()
    cheap.model = "request-model"
    cheap.stream_chat_completion = AsyncMock(return_value="Draft answer")
    original = config.AUTOCHECK_DRAFT_MODEL.__value__

    try:
      config.AUTOCHECK_DRAFT_MODEL.__value__ = "draft-model"
      with patch("research.orchestrate.cheap_llm", return_value=cheap) as cheap_llm:
        draft = await autocheck.generate_draft(chat, llm)
    finally:
      config.AUTOCHECK_DRAFT_MODEL.__value__ = original

    cheap_llm.assert_called_once_with(llm)
    assert cheap.model == "draft-model"
    assert draft == "Draft answer"
    cheap.stream_chat_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_run_audit_uses_audit_model_override(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement helper in utils.py"},
    ])
    llm = MagicMock()
    llm.url = "http://example.com"
    llm.headers = {}
    llm.query_params = {}
    llm.model = "request-model"
    cheap = MagicMock()
    cheap.model = "request-model"
    cheap.chat_completion = AsyncMock(
      return_value={"verdict": "pass", "summary": "Ship it", "findings": []},
    )
    original = config.AUTOCHECK_AUDIT_MODEL.__value__

    try:
      config.AUTOCHECK_AUDIT_MODEL.__value__ = "audit-model"
      with patch("research.orchestrate.cheap_llm", return_value=cheap) as cheap_llm:
        audit, debug = await autocheck.run_audit(chat, llm, "draft text")
    finally:
      config.AUTOCHECK_AUDIT_MODEL.__value__ = original

    cheap_llm.assert_called_once_with(llm)
    assert cheap.model == "audit-model"
    assert audit.verdict == "pass"
    assert debug.verdict == "pass"

  @pytest.mark.asyncio
  async def test_revise_draft_uses_revise_model_override(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement helper in utils.py"},
    ])
    llm = MagicMock()
    llm.model = "request-model"
    cheap = MagicMock()
    cheap.model = "request-model"
    cheap.chat_completion = AsyncMock(return_value="Revised answer with correct path.")
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
    original = config.AUTOCHECK_REVISE_MODEL.__value__

    try:
      config.AUTOCHECK_REVISE_MODEL.__value__ = "revise-model"
      with patch("research.orchestrate.cheap_llm", return_value=cheap) as cheap_llm:
        revised = await autocheck.revise_draft(chat, llm, "Original draft", audit)
    finally:
      config.AUTOCHECK_REVISE_MODEL.__value__ = original

    cheap_llm.assert_called_once_with(llm)
    assert cheap.model == "revise-model"
    assert revised == "Revised answer with correct path."

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

  def test_format_revise_findings_sections_splits_mechanical_from_audit(self):
    mechanical = [
      autocheck.AuditFinding(
        severity="major",
        message="Referenced file does not exist in workspace: src/missing.py",
        fix_hint="Use an existing repo-relative path.",
      )
    ]
    audit = autocheck.AuditResult(
      verdict="revise",
      summary="Fix paths and imports",
      findings=[
        *mechanical,
        autocheck.AuditFinding(
          severity="major",
          message="Missing import",
          fix_hint="Add `import os`",
        ),
      ],
    )

    mechanical_text, audit_text = autocheck.format_revise_findings_sections(
      audit,
      mechanical,
    )

    assert "does not exist in workspace" in mechanical_text
    assert "Missing import" not in mechanical_text
    assert "Missing import" in audit_text
    assert "does not exist in workspace" not in audit_text

  @pytest.mark.asyncio
  async def test_revise_draft_prompt_targets_findings_and_preserves_correct_sections(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement helper in services/boost/src/utils.py"},
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
        fix_hint="Name the target files for each code change.",
      )
    ]
    audit = autocheck.AuditResult(
      verdict="revise",
      summary="Ground code changes in real paths",
      findings=[
        *mechanical,
        autocheck.AuditFinding(
          severity="major",
          message="Wrong file",
          fix_hint="Use services/boost/src/utils.py",
        ),
      ],
    )

    with patch("research.orchestrate.cheap_llm") as cheap_llm:
      cheap = MagicMock()
      cheap.chat_completion = AsyncMock(return_value="Revised answer with correct path.")
      cheap_llm.return_value = cheap

      await autocheck.revise_draft(
        chat,
        llm,
        "Original draft",
        audit,
        mechanical_findings=mechanical,
      )

    kwargs = cheap.chat_completion.await_args.kwargs
    assert kwargs["prompt"] == autocheck.REVISE_PROMPT
    assert "minimal edit" in kwargs["prompt"].lower()
    assert "preserve the user's original intent" in kwargs["prompt"].lower()
    assert "already correct" in kwargs["prompt"].lower()
    assert "mechanical pre-audit blockers" in kwargs["prompt"].lower()
    assert "cites no file paths" in kwargs["mechanical_findings"]
    assert "Wrong file" in kwargs["audit_findings"]
    assert "cites no file paths" not in kwargs["audit_findings"]


class TestAutocheckApply:
  @pytest.mark.asyncio
  async def test_apply_strict_skips_audit_when_workspace_unconfigured(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    original_strict = config.AUTOCHECK_STRICT.__value__
    original_root = config.WORKSPACE_ROOT.__value__
    try:
      config.AUTOCHECK_STRICT.__value__ = True
      config.WORKSPACE_ROOT.__value__ = ""

      with (
        patch.object(autocheck, "generate_draft", new=AsyncMock()) as draft,
        patch.object(autocheck.logger, "error") as log_error,
      ):
        await autocheck.apply(chat, llm)

      draft.assert_not_called()
      log_error.assert_called_once()
      assert "HARBOR_BOOST_AUTOCHECK_STRICT" in log_error.call_args.args[0]
      assert "HARBOR_BOOST_WORKSPACE_ROOT" in log_error.call_args.args[0]
      llm.emit_status.assert_awaited_once_with(
        "Autocheck: skipped (workspace_unconfigured)",
      )
      llm.stream_final_completion.assert_awaited_once()
    finally:
      config.AUTOCHECK_STRICT.__value__ = original_strict
      config.WORKSPACE_ROOT.__value__ = original_root

  @pytest.mark.asyncio
  async def test_apply_passes_through_non_deliverable(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Explain Python dataclasses briefly."},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    with patch.object(autocheck, "generate_draft", new=AsyncMock()) as draft:
      await autocheck.apply(chat, llm)

    draft.assert_not_called()
    llm.emit_status.assert_awaited_once_with("Autocheck: skipped (not_deliverable)")
    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_apply_defers_final_when_configured(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Explain Python dataclasses briefly."},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    with patch.object(autocheck, "generate_draft", new=AsyncMock()) as draft:
      await autocheck.apply(chat, llm, config={"defer_final": True})

    draft.assert_not_called()
    llm.emit_status.assert_awaited_once_with("Autocheck: skipped (not_deliverable)")
    llm.stream_final_completion.assert_not_called()

  @pytest.mark.asyncio
  async def test_apply_anchors_revised_draft_when_defer_final(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
      {"role": "assistant", "content": "Draft implementation"},
    ])
    llm = MagicMock()
    llm.boost_params = {}
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()

    first_audit = autocheck.AuditResult(
      verdict="revise",
      summary="Fix imports",
      findings=[autocheck.AuditFinding(severity="major", message="Missing import")],
    )
    second_audit = autocheck.AuditResult(verdict="pass", summary="Good now")
    first_debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="revise")
    second_debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="pass")
    revised = "Revised implementation"

    with (
      _patch_autocheck_draft_llm(),
      patch.object(autocheck, "gather_workspace_context", new=AsyncMock(return_value="")),
      patch.object(
        autocheck,
        "run_audit",
        new=AsyncMock(side_effect=[(first_audit, first_debug), (second_audit, second_debug)]),
      ),
      patch.object(autocheck, "revise_draft", new=AsyncMock(return_value=revised)),
    ):
      await autocheck.apply(chat, llm, config={"defer_final": True})

    assistants = [
      msg.get("content") or ""
      for msg in chat.history()
      if msg.get("role") == "assistant"
    ]
    assert assistants == [revised]
    llm.emit_message.assert_awaited_once_with(revised)
    llm.stream_final_completion.assert_not_called()

  @pytest.mark.parametrize(
    "gate_reason",
    [
      "disabled",
      "empty_message",
      "research_only",
      "acknowledgment",
      "short_message",
      "continuation",
      "not_deliverable",
      "insufficient_signals",
      "workspace_unconfigured",
    ],
  )
  @pytest.mark.asyncio
  async def test_apply_emits_skipped_status_for_all_gate_reasons(self, gate_reason):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    with (
      patch.object(autocheck, "autocheck_gate_reason", return_value=gate_reason),
      patch.object(autocheck, "generate_draft", new=AsyncMock()) as draft,
    ):
      await autocheck.apply(chat, llm)

    draft.assert_not_called()
    llm.emit_status.assert_awaited_once_with(
      autocheck.format_skipped_status(gate_reason)
    )

  @pytest.mark.asyncio
  async def test_apply_emits_skipped_status_on_empty_message_after_gate(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    with (
      patch.object(autocheck, "autocheck_gate_reason", return_value="triggered"),
      patch("modules.autocheck.orchestrate.last_user_text", return_value=""),
      patch.object(autocheck, "generate_draft", new=AsyncMock()) as draft,
    ):
      await autocheck.apply(chat, llm)

    draft.assert_not_called()
    llm.emit_status.assert_awaited_once_with("Autocheck: skipped (empty_message)")

  @pytest.mark.asyncio
  async def test_apply_emits_skipped_status_on_draft_generation_failure(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    with patch.object(
      autocheck,
      "generate_draft",
      new=AsyncMock(side_effect=RuntimeError("draft down")),
    ):
      await autocheck.apply(chat, llm)

    status_messages = [call.args[0] for call in llm.emit_status.await_args_list]
    assert "Autocheck: drafting..." in status_messages
    assert "Autocheck: skipped (draft_generation_failed)" in status_messages
    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_apply_emits_skipped_status_on_empty_draft(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    with patch.object(autocheck, "generate_draft", new=AsyncMock(return_value="")):
      await autocheck.apply(chat, llm)

    status_messages = [call.args[0] for call in llm.emit_status.await_args_list]
    assert "Autocheck: drafting..." in status_messages
    assert "Autocheck: skipped (empty_draft)" in status_messages
    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_apply_runs_mechanical_preaudit_before_llm_audit(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.boost_params = {}
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()

    audit = autocheck.AuditResult(verdict="pass", summary="Ship it")
    debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="pass")
    mechanical = [
      autocheck.AuditFinding(severity="major", message="Mechanical blocker"),
    ]

    with (
      _patch_autocheck_draft_llm(),
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

    audit = autocheck.AuditResult(verdict="pass", summary="Ship it")
    debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="pass")

    with (
      _patch_autocheck_draft_llm(),
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

    first_audit = autocheck.AuditResult(
      verdict="revise",
      summary="Fix imports",
      findings=[autocheck.AuditFinding(severity="major", message="Missing import")],
    )
    second_audit = autocheck.AuditResult(verdict="pass", summary="Good now")
    first_debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="revise")
    second_debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="pass")

    with (
      _patch_autocheck_draft_llm(),
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
  async def test_apply_reruns_mechanical_preaudit_after_revise(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.boost_params = {}
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()

    first_audit = autocheck.AuditResult(
      verdict="revise",
      summary="Fix paths",
      findings=[autocheck.AuditFinding(severity="major", message="Wrong path")],
    )
    second_audit = autocheck.AuditResult(verdict="pass", summary="Good now")
    first_debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="revise")
    second_debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="pass")
    stale_blocker = [
      autocheck.AuditFinding(
        severity="major",
        message="Draft contains code blocks but cites no file paths",
      ),
    ]
    refreshed = ([], [])

    with (
      _patch_autocheck_draft_llm(),
      patch.object(autocheck, "gather_workspace_context", new=AsyncMock(return_value="")),
      patch.object(
        autocheck,
        "run_mechanical_preaudit",
        new=AsyncMock(side_effect=[("", stale_blocker), refreshed]),
      ) as preaudit,
      patch.object(
        autocheck,
        "run_audit",
        new=AsyncMock(side_effect=[(first_audit, first_debug), (second_audit, second_debug)]),
      ) as run_audit,
      patch.object(
        autocheck,
        "revise_draft",
        new=AsyncMock(return_value="Revised with `services/boost/src/utils.py`."),
      ),
    ):
      await autocheck.apply(chat, llm)

    assert preaudit.await_count == 2
    assert run_audit.await_args_list[1].kwargs["mechanical_findings"] == []

  @pytest.mark.asyncio
  async def test_apply_appends_audit_footer_when_show_audit_enabled(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.boost_params = {"show_audit": "true"}
    llm.emit_status = AsyncMock()
    llm.emit_artifact = AsyncMock()
    llm.emit_message = AsyncMock()

    audit = autocheck.AuditResult(verdict="pass", summary="Ship it")
    debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="pass")

    with (
      _patch_autocheck_draft_llm(),
      patch.object(autocheck, "gather_workspace_context", new=AsyncMock(return_value="")),
      patch.object(autocheck, "run_audit", new=AsyncMock(return_value=(audit, debug))),
    ):
      await autocheck.apply(chat, llm)

    llm.emit_artifact.assert_awaited_once()
    artifact_html = llm.emit_artifact.await_args.args[0]
    assert "<table>" in artifact_html
    assert "Ship it" in artifact_html
    assert llm.emit_artifact.await_args.kwargs.get("wait") is False

    emitted = llm.emit_message.await_args.args[0]
    assert emitted.startswith("Draft implementation")
    assert "Autocheck: pass (0 findings)" in emitted
    assert "Ship it" in emitted

  @pytest.mark.asyncio
  async def test_apply_skips_audit_artifact_when_show_audit_disabled(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.boost_params = {}
    llm.emit_status = AsyncMock()
    llm.emit_artifact = AsyncMock()
    llm.emit_message = AsyncMock()

    audit = autocheck.AuditResult(verdict="pass", summary="Ship it")
    debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="pass")

    with (
      _patch_autocheck_draft_llm(),
      patch.object(autocheck, "gather_workspace_context", new=AsyncMock(return_value="")),
      patch.object(autocheck, "run_audit", new=AsyncMock(return_value=(audit, debug))),
    ):
      await autocheck.apply(chat, llm)

    llm.emit_artifact.assert_not_called()

  @pytest.mark.asyncio
  async def test_apply_explores_workspace_when_root_configured(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Fix bug in services/boost/src/main.py"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()

    audit = autocheck.AuditResult(verdict="pass", summary="OK")
    original_root = config.WORKSPACE_ROOT.__value__

    try:
      config.WORKSPACE_ROOT.__value__ = "/workspace"

      with (
        _patch_autocheck_draft_llm("Draft with services/boost/src/main.py"),
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
  async def test_apply_strict_mode_allows_second_revise_pass(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.boost_params = {}
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()

    revise_audit = autocheck.AuditResult(
      verdict="revise",
      summary="Fix imports",
      findings=[autocheck.AuditFinding(severity="major", message="Missing import")],
    )
    pass_audit = autocheck.AuditResult(verdict="pass", summary="Good now")
    revise_debug = autocheck.AuditDebug(
      triggered=True,
      gate_reason="triggered",
      verdict="revise",
    )
    pass_debug = autocheck.AuditDebug(
      triggered=True,
      gate_reason="triggered",
      verdict="pass",
    )
    original_revise = config.AUTOCHECK_MAX_REVISE_PASSES.__value__
    original_strict = config.AUTOCHECK_STRICT.__value__
    original_root = config.WORKSPACE_ROOT.__value__

    try:
      config.AUTOCHECK_MAX_REVISE_PASSES.__value__ = 1
      config.AUTOCHECK_STRICT.__value__ = True
      config.WORKSPACE_ROOT.__value__ = "/workspace"
      with (
        _patch_autocheck_draft_llm(),
        patch.object(autocheck, "gather_workspace_context", new=AsyncMock(return_value="")),
        patch.object(
          autocheck,
          "explore_workspace_with_tools",
          new=AsyncMock(return_value=("", [])),
        ),
        patch.object(
          autocheck,
          "run_audit",
          new=AsyncMock(
            side_effect=[
              (revise_audit, revise_debug),
              (revise_audit, revise_debug),
              (pass_audit, pass_debug),
            ],
          ),
        ),
        patch.object(
          autocheck,
          "revise_draft",
          new=AsyncMock(side_effect=["First revision", "Second revision"]),
        ) as revise,
      ):
        await autocheck.apply(chat, llm)
    finally:
      config.AUTOCHECK_MAX_REVISE_PASSES.__value__ = original_revise
      config.AUTOCHECK_STRICT.__value__ = original_strict
      config.WORKSPACE_ROOT.__value__ = original_root

    assert revise.await_count == 2
    status_messages = [call.args[0] for call in llm.emit_status.await_args_list]
    assert "Autocheck: revising (1/2)..." in status_messages
    assert "Autocheck: revising (2/2)..." in status_messages
    llm.emit_message.assert_awaited_once_with("Second revision")

  @pytest.mark.asyncio
  async def test_apply_non_strict_stops_after_configured_revise_passes(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.boost_params = {}
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()

    revise_audit = autocheck.AuditResult(
      verdict="revise",
      summary="Fix imports",
      findings=[autocheck.AuditFinding(severity="major", message="Missing import")],
    )
    revise_debug = autocheck.AuditDebug(
      triggered=True,
      gate_reason="triggered",
      verdict="revise",
    )
    original_revise = config.AUTOCHECK_MAX_REVISE_PASSES.__value__
    original_strict = config.AUTOCHECK_STRICT.__value__

    try:
      config.AUTOCHECK_MAX_REVISE_PASSES.__value__ = 1
      config.AUTOCHECK_STRICT.__value__ = False
      with (
        _patch_autocheck_draft_llm(),
        patch.object(autocheck, "gather_workspace_context", new=AsyncMock(return_value="")),
        patch.object(
          autocheck,
          "run_audit",
          new=AsyncMock(
            side_effect=[
              (revise_audit, revise_debug),
              (revise_audit, revise_debug),
            ],
          ),
        ),
        patch.object(
          autocheck,
          "revise_draft",
          new=AsyncMock(return_value="Revised implementation"),
        ) as revise,
      ):
        await autocheck.apply(chat, llm)
    finally:
      config.AUTOCHECK_MAX_REVISE_PASSES.__value__ = original_revise
      config.AUTOCHECK_STRICT.__value__ = original_strict

    revise.assert_awaited_once()
    status_messages = [call.args[0] for call in llm.emit_status.await_args_list]
    assert "Autocheck: revising (1/1)..." in status_messages
    assert "Autocheck: revising (2/2)..." not in status_messages
    llm.emit_message.assert_awaited_once_with("Revised implementation")

  @pytest.mark.asyncio
  async def test_apply_prepends_strict_warning_when_blockers_remain(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.boost_params = {}
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()

    first_audit = autocheck.AuditResult(
      verdict="revise",
      summary="Fix imports",
      findings=[autocheck.AuditFinding(severity="major", message="Missing import")],
    )
    second_audit = autocheck.AuditResult(
      verdict="revise",
      summary="Still missing import",
      findings=[autocheck.AuditFinding(severity="major", message="Missing import")],
    )
    first_debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="revise")
    second_debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="revise")
    third_debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="revise")
    original_strict = config.AUTOCHECK_STRICT.__value__
    original_revise = config.AUTOCHECK_MAX_REVISE_PASSES.__value__
    original_root = config.WORKSPACE_ROOT.__value__

    try:
      config.AUTOCHECK_MAX_REVISE_PASSES.__value__ = 1
      config.AUTOCHECK_STRICT.__value__ = True
      config.WORKSPACE_ROOT.__value__ = "/workspace"
      with (
        _patch_autocheck_draft_llm(),
        patch.object(autocheck, "gather_workspace_context", new=AsyncMock(return_value="")),
        patch.object(
          autocheck,
          "explore_workspace_with_tools",
          new=AsyncMock(return_value=("", [])),
        ),
        patch.object(
          autocheck,
          "run_audit",
          new=AsyncMock(
            side_effect=[
              (first_audit, first_debug),
              (second_audit, second_debug),
              (second_audit, third_debug),
            ],
          ),
        ),
        patch.object(
          autocheck,
          "revise_draft",
          new=AsyncMock(side_effect=["First revision", "Second revision"]),
        ) as revise,
      ):
        await autocheck.apply(chat, llm)
    finally:
      config.AUTOCHECK_STRICT.__value__ = original_strict
      config.AUTOCHECK_MAX_REVISE_PASSES.__value__ = original_revise
      config.WORKSPACE_ROOT.__value__ = original_root

    assert revise.await_count == 2
    status_messages = [call.args[0] for call in llm.emit_status.await_args_list]
    assert "Autocheck: revising (1/2)..." in status_messages
    assert "Autocheck: revising (2/2)..." in status_messages
    emitted = llm.emit_message.await_args.args[0]
    assert emitted.startswith("> **Autocheck warning:**")
    assert "Unresolved critical or major findings remain after revision" in emitted
    assert "Second revision" in emitted
    assert "[major] Missing import" in emitted

  @pytest.mark.asyncio
  async def test_apply_skips_strict_warning_when_disabled(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.boost_params = {}
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()

    first_audit = autocheck.AuditResult(
      verdict="revise",
      summary="Fix imports",
      findings=[autocheck.AuditFinding(severity="major", message="Missing import")],
    )
    second_audit = autocheck.AuditResult(
      verdict="revise",
      summary="Still missing import",
      findings=[autocheck.AuditFinding(severity="major", message="Missing import")],
    )
    first_debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="revise")
    second_debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="revise")
    original_strict = config.AUTOCHECK_STRICT.__value__

    try:
      config.AUTOCHECK_STRICT.__value__ = False
      with (
        _patch_autocheck_draft_llm(),
        patch.object(autocheck, "gather_workspace_context", new=AsyncMock(return_value="")),
        patch.object(
          autocheck,
          "run_audit",
          new=AsyncMock(side_effect=[(first_audit, first_debug), (second_audit, second_debug)]),
        ),
        patch.object(
          autocheck,
          "revise_draft",
          new=AsyncMock(return_value="Revised implementation"),
        ),
      ):
        await autocheck.apply(chat, llm)
    finally:
      config.AUTOCHECK_STRICT.__value__ = original_strict

    emitted = llm.emit_message.await_args.args[0]
    assert emitted == "Revised implementation"
    assert "Autocheck warning" not in emitted

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

    with (
      _patch_autocheck_draft_llm(),
      patch.object(autocheck, "gather_workspace_context", new=AsyncMock(return_value="")),
      patch.object(autocheck, "run_audit", new=AsyncMock(side_effect=RuntimeError("audit down"))),
    ):
      await autocheck.apply(chat, llm)

    status_messages = [call.args[0] for call in llm.emit_status.await_args_list]
    assert "Autocheck: skipped (audit_failed)" in status_messages
    llm.emit_message.assert_awaited_once_with("Draft implementation")
    llm.stream_final_completion.assert_not_called()