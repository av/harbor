"""Unit tests for shared agentic module infrastructure."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chat as ch
import config
import deliverable
from research.brief import (
  RESEARCH_UNAVAILABLE_NOTE,
  ResearchBrief,
  finalize_brief,
  has_usable_research,
  highlight_versions,
  render_to_system,
)
from research.budget import BudgetExceeded, ResearchBudget, budget_from_config
from research.fetch import (
  is_read_failure_result,
  is_search_failure_result,
  read_url,
  require_http_url,
  trim,
  web_search,
)
from modules import tools


class TestResearchFetch:
  def test_trim_truncates_long_text(self):
    text = "x" * 20
    result = trim(text, 10)
    assert result.startswith("x" * 10)
    assert "truncated" in result

  def test_require_http_url_rejects_private_hosts(self):
    with pytest.raises(ValueError, match="internal or private"):
      require_http_url("http://127.0.0.1/test")

  def test_require_http_url_accepts_public_https(self):
    assert require_http_url("https://example.com/docs") == "https://example.com/docs"

  def test_is_search_failure_result_detects_errors_and_empty(self):
    assert is_search_failure_result("")
    assert is_search_failure_result("No results found.")
    assert is_search_failure_result("Web search failed: timeout")
    assert is_search_failure_result("Web search unavailable: configure API key")
    assert not is_search_failure_result("1. [Docs](https://example.com) (Date: N/A)\nSnippet")

  def test_is_read_failure_result_detects_errors(self):
    assert is_read_failure_result("Could not read URL: https://example.com: timeout")
    assert not is_read_failure_result("Page body text")

  @pytest.mark.asyncio
  async def test_read_url_returns_failure_for_private_hosts(self):
    result = await read_url("http://127.0.0.1/test")
    assert is_read_failure_result(result)
    assert "127.0.0.1" in result

  @pytest.mark.asyncio
  async def test_read_url_returns_failure_when_all_readers_fail(self):
    with patch("research.fetch._read_with_jina", new=AsyncMock(side_effect=RuntimeError("jina down"))):
      with patch("research.fetch._read_direct", new=AsyncMock(side_effect=RuntimeError("http down"))):
        result = await read_url("https://example.com/docs")

    assert is_read_failure_result(result)
    assert "http down" in result

  @pytest.mark.asyncio
  async def test_web_search_returns_failure_message_on_provider_error(self):
    with patch("research.fetch._search_tavily", new=AsyncMock(side_effect=RuntimeError("provider down"))):
      original = config.TAVILY_API_KEY.__value__
      try:
        config.TAVILY_API_KEY.__value__ = "test-key"
        result = await web_search("python asyncio")
      finally:
        config.TAVILY_API_KEY.__value__ = original

    assert is_search_failure_result(result)
    assert "provider down" in result

  @pytest.mark.asyncio
  async def test_web_search_retries_once_on_transient_failure(self):
    search_mock = AsyncMock(
      side_effect=[
        httpx.ConnectError("connection reset"),
        "1. [Docs](https://example.com) (Date: N/A)\nSnippet",
      ],
    )
    with (
      patch("research.fetch._search_tavily", new=search_mock),
      patch("research.fetch.asyncio.sleep", new=AsyncMock()) as sleep_mock,
    ):
      original = config.TAVILY_API_KEY.__value__
      try:
        config.TAVILY_API_KEY.__value__ = "test-key"
        result = await web_search("python asyncio")
      finally:
        config.TAVILY_API_KEY.__value__ = original

    assert search_mock.await_count == 2
    sleep_mock.assert_awaited_once_with(1.0)
    assert result == "1. [Docs](https://example.com) (Date: N/A)\nSnippet"

  @pytest.mark.asyncio
  async def test_web_search_does_not_retry_non_transient_failures(self):
    search_mock = AsyncMock(side_effect=RuntimeError("provider down"))
    with (
      patch("research.fetch._search_tavily", new=search_mock),
      patch("research.fetch.asyncio.sleep", new=AsyncMock()) as sleep_mock,
    ):
      original = config.TAVILY_API_KEY.__value__
      try:
        config.TAVILY_API_KEY.__value__ = "test-key"
        result = await web_search("python asyncio")
      finally:
        config.TAVILY_API_KEY.__value__ = original

    assert search_mock.await_count == 1
    sleep_mock.assert_not_awaited()
    assert is_search_failure_result(result)
    assert "provider down" in result

  @pytest.mark.asyncio
  async def test_read_url_retries_jina_once_on_transient_failure(self):
    jina_mock = AsyncMock(
      side_effect=[
        httpx.ReadTimeout("read timed out"),
        "page content from jina",
      ],
    )
    direct_mock = AsyncMock(return_value="should not be used")

    with (
      patch("research.fetch._read_with_jina", new=jina_mock),
      patch("research.fetch._read_direct", new=direct_mock),
      patch("research.fetch.asyncio.sleep", new=AsyncMock()) as sleep_mock,
    ):
      result = await read_url("https://example.com/docs")

    assert jina_mock.await_count == 2
    direct_mock.assert_not_awaited()
    sleep_mock.assert_awaited_once_with(1.0)
    assert result == "page content from jina"

  @pytest.mark.asyncio
  async def test_read_url_retries_direct_once_on_transient_failure(self):
    jina_mock = AsyncMock(side_effect=ValueError("jina unavailable"))
    direct_mock = AsyncMock(
      side_effect=[
        httpx.ConnectError("connection reset"),
        "page content from direct http",
      ],
    )

    with (
      patch("research.fetch._read_with_jina", new=jina_mock),
      patch("research.fetch._read_direct", new=direct_mock),
      patch("research.fetch.asyncio.sleep", new=AsyncMock()) as sleep_mock,
    ):
      result = await read_url("https://example.com/docs")

    assert jina_mock.await_count == 1
    assert direct_mock.await_count == 2
    sleep_mock.assert_awaited_once_with(1.0)
    assert result == "page content from direct http"


class TestResearchBrief:
  def test_render_to_system_includes_sections(self):
    brief = ResearchBrief(
      query="python asyncio",
      searches=[{"title": "Docs", "url": "https://example.com", "snippet": "async guide"}],
      pages=[{"title": "PEP", "url": "https://peps.python.org", "snippet": "spec text"}],
      notes=["Prefer stdlib patterns"],
    )

    rendered = render_to_system(brief)
    assert "<research_brief>" in rendered
    assert "<query>python asyncio</query>" in rendered
    assert "<search_results>" in rendered
    assert "async guide" in rendered
    assert "<page_content>" in rendered
    assert "spec text" in rendered
    assert "Prefer stdlib patterns" in rendered

  def test_add_search_results_parses_formatted_lines(self):
    brief = ResearchBrief()
    brief.add_search_results(
      "test query",
      "1. [Title](https://example.com) (Date: N/A)\nSnippet text",
    )
    assert brief.query == "test query"
    assert len(brief.searches) == 1
    assert brief.searches[0].title == "Title"
    assert brief.searches[0].url == "https://example.com"
    assert brief.searches[0].snippet == "Snippet text"

  def test_has_usable_research_false_when_only_failures_present(self):
    brief = ResearchBrief()
    brief.add_search_results("test query", "Web search failed: timeout")
    assert not has_usable_research(brief)

  def test_finalize_brief_adds_research_unavailable_note(self):
    brief = ResearchBrief(query="python asyncio")
    brief.add_search_results("python asyncio", "No results found.")
    finalized = finalize_brief(brief)
    assert RESEARCH_UNAVAILABLE_NOTE in finalized.notes

  def test_finalize_brief_skips_note_when_usable_research_exists(self):
    brief = ResearchBrief()
    brief.add_search_results(
      "python asyncio",
      "1. [Docs](https://example.com) (Date: N/A)\nSnippet",
    )
    finalized = finalize_brief(brief)
    assert RESEARCH_UNAVAILABLE_NOTE not in finalized.notes

  def test_render_to_system_uses_dash_bullets_for_synthesized_sections(self):
    brief = ResearchBrief(
      query="fastapi migration",
      facts=["Routing hooks removed in 0.115"],
      uncertainties=["Verify middleware order in official docs"],
      do_not_assume=["Do not assume plugins support 0.115"],
      recommendation="Pin FastAPI 0.115 and run the migration checklist.",
    )

    rendered = render_to_system(brief)

    assert "<facts>\n- Routing hooks removed in `0.115`\n</facts>" in rendered
    assert (
      "<uncertainties>\n- Verify middleware order in official docs\n</uncertainties>"
      in rendered
    )
    assert (
      "<do_not_assume>\n- Do not assume plugins support `0.115`\n</do_not_assume>"
      in rendered
    )

  def test_highlight_versions_wraps_semver_and_api_dates(self):
    assert highlight_versions("Migrate from 0.100 to 0.115") == (
      "Migrate from `0.100` to `0.115`"
    )
    assert highlight_versions("Stripe API 2024-06-20 changes checkout fields") == (
      "Stripe API `2024-06-20` changes checkout fields"
    )
    assert highlight_versions("Already wrapped `1.2.3` stays intact") == (
      "Already wrapped `1.2.3` stays intact"
    )

  def test_highlight_versions_preserves_dotted_filenames(self):
    assert highlight_versions("Deploy artifact v1.2.3.py to staging") == (
      "Deploy artifact v1.2.3.py to staging"
    )
    assert highlight_versions("Pin requirements.txt to 2.1.0") == (
      "Pin requirements.txt to `2.1.0`"
    )

  def test_render_to_system_highlights_versions_in_recommendation(self):
    brief = ResearchBrief(
      recommendation="Upgrade to FastAPI 0.115 before changing middleware.",
    )

    rendered = render_to_system(brief)

    assert "<recommendation>Upgrade to FastAPI `0.115` before changing middleware.</recommendation>" in rendered


class TestResearchBudget:
  def test_budget_enforces_search_limit(self):
    budget = ResearchBudget(max_searches=1)
    budget.record_search()
    with pytest.raises(BudgetExceeded):
      budget.record_search()

  def test_budget_trims_to_remaining_chars(self):
    budget = ResearchBudget(max_chars=5)
    trimmed = budget.trim_to_remaining("abcdef")
    assert trimmed == "abcde"
    assert budget.chars_used == 5

  def test_budget_from_config_uses_module_defaults(self):
    original = (
      config.CAVEMAN_MAX_SEARCHES.__value__,
      config.CAVEMAN_MAX_URL_READS.__value__,
      config.CAVEMAN_MAX_CHARS.__value__,
    )
    try:
      config.CAVEMAN_MAX_SEARCHES.__value__ = 7
      config.CAVEMAN_MAX_URL_READS.__value__ = 3
      config.CAVEMAN_MAX_CHARS.__value__ = 12000
      budget = budget_from_config("caveman")
      assert budget.max_searches == 7
      assert budget.max_url_reads == 3
      assert budget.max_chars == 12000
    finally:
      (
        config.CAVEMAN_MAX_SEARCHES.__value__,
        config.CAVEMAN_MAX_URL_READS.__value__,
        config.CAVEMAN_MAX_CHARS.__value__,
      ) = original


class TestDeliverableGate:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  def test_detects_implementation_request(self):
    assert deliverable.is_coding_deliverable(
      self._chat("Please implement a retry helper in services/boost/src/utils.py")
    )

  def test_detects_code_block_request(self):
    assert deliverable.is_coding_deliverable(
      self._chat("Fix this function:\n```python\ndef add(a, b):\n  return a - b\n```")
    )

  def test_skips_pure_explanation_request(self):
    assert not deliverable.is_coding_deliverable(
      self._chat("Explain what asyncio.gather does in plain English.")
    )

  def test_deliverable_signals_count_multiple_markers(self):
    chat = self._chat("Implement retry helper in services/boost/src/utils.py")
    signals = deliverable.deliverable_signals(
      chat.match_one(role="user", index=-1).content,
    )
    assert "coding_keyword" in signals
    assert "file_path" in signals
    assert deliverable.count_deliverable_signals(chat) >= 2

  def test_explicit_done_signal_detects_completion_phrases(self):
    assert deliverable.has_explicit_done_signal("We're done, ship it.")
    assert deliverable.has_explicit_done_signal("Looks good.")
    assert not deliverable.has_explicit_done_signal("Implement the helper next.")

  def test_completion_trigger_requires_prior_coding_context(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement helper in services/boost/src/utils.py"},
      {"role": "assistant", "content": "Done."},
      {"role": "user", "content": "Looks good."},
    ])
    assert deliverable.has_prior_coding_context(chat)
    assert deliverable.is_completion_trigger(chat)

  def test_completion_trigger_false_for_casual_done_phrase(self):
    chat = self._chat("Ship it")
    assert not deliverable.has_prior_coding_context(chat)
    assert not deliverable.is_completion_trigger(chat)

  def test_recent_finish_tool_call_detected_in_history(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Add tests in services/boost/tests/test_utils.py"},
      {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
          "id": "call_finish",
          "type": "function",
          "function": {"name": "finish", "arguments": "{}"},
        }],
      },
      {"role": "tool", "content": "Tests added.", "tool_call_id": "call_finish"},
      {"role": "user", "content": "ok"},
    ])
    assert deliverable.has_recent_finish_tool_call(chat)
    assert deliverable.is_completion_trigger(chat)


class TestDeliverableBorderlineCases:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  @pytest.mark.parametrize(
    "message",
    [
      "thanks for the help!",
      "ok thanks",
      "looks good, thanks",
      "thank you so much",
      "perfect, that works",
    ],
  )
  def test_acknowledgments_are_not_deliverable(self, message: str):
    assert deliverable.is_acknowledgment(message)
    assert not deliverable.is_coding_deliverable(self._chat(message))
    assert deliverable.deliverable_signals(message) == []

  def test_ok_with_followup_request_is_not_acknowledgment(self):
    message = "ok, but fix the timeout handling next"
    assert not deliverable.is_acknowledgment(message)
    assert deliverable.is_coding_deliverable(self._chat(message))

  @pytest.mark.parametrize(
    "message",
    [
      "Explain this function in services/boost/src/utils.py",
      "What does this code do?\n```python\ndef retry():\n  pass\n```",
      "Walk me through how services/boost/src/utils.py handles retries",
      "Can you explain why this test fails?\n```python\ndef test_retry():\n  assert False\n```",
    ],
  )
  def test_explain_code_is_not_deliverable(self, message: str):
    assert deliverable.has_explain_intent(message)
    assert not deliverable.is_coding_deliverable(self._chat(message))
    assert deliverable.deliverable_signals(message) == []

  @pytest.mark.parametrize(
    "message",
    [
      "Fix this function in services/boost/src/utils.py",
      "Debug the failing test in services/boost/tests/test_utils.py",
      "services/boost/src/utils.py is broken — patch the retry loop",
    ],
  )
  def test_fix_code_remains_deliverable(self, message: str):
    assert deliverable.is_coding_deliverable(self._chat(message))

  @pytest.mark.parametrize(
    "message",
    [
      "What changed in Python 3.13 asyncio semantics?",
      "Compare FastAPI 0.100 vs 0.115 migration paths",
      "What is the Stripe checkout session API endpoint response format?",
      "How do I migrate from Kubernetes 1.29 to 1.30?",
    ],
  )
  def test_research_questions_are_not_deliverable(self, message: str):
    assert deliverable.has_research_signals(message)
    assert not deliverable.is_coding_deliverable(self._chat(message))
    assert deliverable.is_research_only_turn(self._chat(message))

  def test_implementation_with_research_signals_stays_deliverable(self):
    message = (
      "Implement OAuth against the latest Stripe API documentation for checkout sessions."
    )
    assert deliverable.has_research_signals(message)
    assert deliverable.is_coding_deliverable(self._chat(message))

  @pytest.mark.parametrize(
    "message",
    [
      "latest Stripe API docs",
      "Python 3.13 migration guide",
      "FastAPI 0.115 breaking changes",
      "v1.2.3 to v2.0.0 upgrade path",
    ],
  )
  def test_research_signal_keywords_detected(self, message: str):
    assert deliverable.has_research_signals(message)


class TestWorkspaceFileTool:
  def _with_workspace_root(self, value: str):
    original = config.WORKSPACE_ROOT.__value__
    config.WORKSPACE_ROOT.__value__ = value
    return original

  def test_workspace_path_jail(self):
    with tempfile.TemporaryDirectory() as workspace:
      original = self._with_workspace_root(workspace)
      try:
        with pytest.raises(ValueError, match="stay inside the workspace root"):
          tools._workspace_path("../outside.txt")
      finally:
        config.WORKSPACE_ROOT.__value__ = original

  def test_read_workspace_file_reads_file(self):
    with tempfile.TemporaryDirectory() as workspace:
      target = Path(workspace) / "src" / "main.py"
      target.parent.mkdir(parents=True)
      target.write_text("print('ok')", encoding="utf-8")

      original_root = self._with_workspace_root(workspace)
      original_max = config.WORKSPACE_FILE_MAX_CHARS.__value__
      try:
        config.WORKSPACE_FILE_MAX_CHARS.__value__ = 1000
        import asyncio
        content = asyncio.run(tools.read_workspace_file("src/main.py"))
      finally:
        config.WORKSPACE_ROOT.__value__ = original_root
        config.WORKSPACE_FILE_MAX_CHARS.__value__ = original_max

    assert content == "print('ok')"

  def test_read_workspace_file_requires_workspace_root(self):
    original = self._with_workspace_root("")
    try:
      with pytest.raises(ValueError, match="Workspace root is not configured"):
        tools._workspace_path("README.md")
    finally:
      config.WORKSPACE_ROOT.__value__ = original

  def test_selected_tools_includes_workspace_reader_when_configured(self):
    original = self._with_workspace_root("/workspace")
    try:
      selected = tools._selected_tools(["read_workspace_file"])
      assert "read_workspace_file" in selected
    finally:
      config.WORKSPACE_ROOT.__value__ = original

  def test_selected_tools_omits_workspace_reader_when_unconfigured(self):
    original = self._with_workspace_root("")
    try:
      selected = tools._selected_tools(["read_workspace_file"])
      assert "read_workspace_file" not in selected
    finally:
      config.WORKSPACE_ROOT.__value__ = original

  def test_grep_workspace_finds_pattern(self):
    with tempfile.TemporaryDirectory() as workspace:
      target = Path(workspace) / "src" / "main.py"
      target.parent.mkdir(parents=True)
      target.write_text("def hello_world():\n    return 1\n", encoding="utf-8")

      original_root = self._with_workspace_root(workspace)
      original_max = config.WORKSPACE_GREP_MAX_MATCHES.__value__
      try:
        config.WORKSPACE_GREP_MAX_MATCHES.__value__ = 10
        import asyncio
        result = asyncio.run(tools.grep_workspace("hello_world", glob="*.py"))
      finally:
        config.WORKSPACE_ROOT.__value__ = original_root
        config.WORKSPACE_GREP_MAX_MATCHES.__value__ = original_max

    assert "src/main.py:1:def hello_world():" in result

  def test_grep_workspace_respects_max_matches(self):
    with tempfile.TemporaryDirectory() as workspace:
      target = Path(workspace) / "notes.txt"
      target.write_text("match\nmatch\nmatch\n", encoding="utf-8")

      original_root = self._with_workspace_root(workspace)
      try:
        import asyncio
        result = asyncio.run(tools.grep_workspace("match", max_matches=2))
      finally:
        config.WORKSPACE_ROOT.__value__ = original_root

    assert result.count("notes.txt:") == 2
    assert "truncated to 2 matches" in result

  def test_grep_workspace_path_jail(self):
    with tempfile.TemporaryDirectory() as workspace:
      original = self._with_workspace_root(workspace)
      try:
        with pytest.raises(ValueError, match="stay inside the workspace root"):
          tools._workspace_search_path("../outside")
      finally:
        config.WORKSPACE_ROOT.__value__ = original

  def test_grep_workspace_requires_workspace_root(self):
    original = self._with_workspace_root("")
    try:
      with pytest.raises(ValueError, match="Workspace root is not configured"):
        tools._workspace_search_path(".")
    finally:
      config.WORKSPACE_ROOT.__value__ = original

  def test_selected_tools_includes_grep_when_configured(self):
    original = self._with_workspace_root("/workspace")
    try:
      selected = tools._selected_tools(["grep_workspace"])
      assert "grep_workspace" in selected
    finally:
      config.WORKSPACE_ROOT.__value__ = original

  def test_selected_tools_omits_grep_when_unconfigured(self):
    original = self._with_workspace_root("")
    try:
      selected = tools._selected_tools(["grep_workspace"])
      assert "grep_workspace" not in selected
    finally:
      config.WORKSPACE_ROOT.__value__ = original

  def test_write_workspace_file_writes_file(self):
    with tempfile.TemporaryDirectory() as workspace:
      original_root = self._with_workspace_root(workspace)
      original_max = config.WORKSPACE_FILE_MAX_CHARS.__value__
      try:
        config.WORKSPACE_FILE_MAX_CHARS.__value__ = 1000
        import asyncio
        result = asyncio.run(
          tools.write_workspace_file("src/main.py", "print('ok')"),
        )
        content = Path(workspace, "src", "main.py").read_text(encoding="utf-8")
      finally:
        config.WORKSPACE_ROOT.__value__ = original_root
        config.WORKSPACE_FILE_MAX_CHARS.__value__ = original_max

    assert content == "print('ok')"
    assert "Wrote" in result

  def test_write_workspace_file_enforces_size_cap(self):
    with tempfile.TemporaryDirectory() as workspace:
      original_root = self._with_workspace_root(workspace)
      original_max = config.WORKSPACE_FILE_MAX_CHARS.__value__
      try:
        config.WORKSPACE_FILE_MAX_CHARS.__value__ = 5
        import asyncio
        with pytest.raises(ValueError, match="content exceeds 5 characters"):
          asyncio.run(tools.write_workspace_file("big.txt", "123456"))
      finally:
        config.WORKSPACE_ROOT.__value__ = original_root
        config.WORKSPACE_FILE_MAX_CHARS.__value__ = original_max

  def test_write_workspace_file_path_jail(self):
    with tempfile.TemporaryDirectory() as workspace:
      original = self._with_workspace_root(workspace)
      try:
        import asyncio
        with pytest.raises(ValueError, match="stay inside the workspace root"):
          asyncio.run(tools.write_workspace_file("../outside.txt", "nope"))
      finally:
        config.WORKSPACE_ROOT.__value__ = original

  def test_write_workspace_file_requires_workspace_root(self):
    original = self._with_workspace_root("")
    try:
      import asyncio
      with pytest.raises(ValueError, match="Workspace root is not configured"):
        asyncio.run(tools.write_workspace_file("README.md", "hello"))
    finally:
      config.WORKSPACE_ROOT.__value__ = original

  def test_selected_tools_includes_workspace_writer_when_configured(self):
    original = self._with_workspace_root("/workspace")
    try:
      selected = tools._selected_tools(["write_workspace_file"])
      assert "write_workspace_file" in selected
    finally:
      config.WORKSPACE_ROOT.__value__ = original

  def test_selected_tools_omits_workspace_writer_when_unconfigured(self):
    original = self._with_workspace_root("")
    try:
      selected = tools._selected_tools(["write_workspace_file"])
      assert "write_workspace_file" not in selected
    finally:
      config.WORKSPACE_ROOT.__value__ = original

  def test_default_tools_omits_workspace_writer(self):
    original = self._with_workspace_root("/workspace")
    try:
      selected = tools._selected_tools()
      assert "write_workspace_file" not in selected
    finally:
      config.WORKSPACE_ROOT.__value__ = original

  def test_list_workspace_files_lists_files(self):
    with tempfile.TemporaryDirectory() as workspace:
      src = Path(workspace) / "src"
      src.mkdir(parents=True)
      (src / "main.py").write_text("print(1)", encoding="utf-8")
      (src / "util.py").write_text("print(2)", encoding="utf-8")
      (Path(workspace) / "README.md").write_text("hi", encoding="utf-8")

      original_root = self._with_workspace_root(workspace)
      try:
        import asyncio
        result = asyncio.run(tools.list_workspace_files(path="src", glob="*.py"))
      finally:
        config.WORKSPACE_ROOT.__value__ = original_root

    assert "src/main.py" in result
    assert "src/util.py" in result
    assert "README.md" not in result

  def test_list_workspace_files_respects_max_entries(self):
    with tempfile.TemporaryDirectory() as workspace:
      for index in range(5):
        (Path(workspace) / f"file{index}.txt").write_text("x", encoding="utf-8")

      original_root = self._with_workspace_root(workspace)
      try:
        import asyncio
        result = asyncio.run(tools.list_workspace_files(max_entries=3))
      finally:
        config.WORKSPACE_ROOT.__value__ = original_root

    assert result.count(".txt") == 3
    assert "truncated to 3 entries" in result

  def test_list_workspace_files_path_jail(self):
    with tempfile.TemporaryDirectory() as workspace:
      original = self._with_workspace_root(workspace)
      try:
        with pytest.raises(ValueError, match="stay inside the workspace root"):
          tools._workspace_search_path("../outside")
      finally:
        config.WORKSPACE_ROOT.__value__ = original

  def test_list_workspace_files_requires_workspace_root(self):
    original = self._with_workspace_root("")
    try:
      import asyncio
      with pytest.raises(ValueError, match="Workspace root is not configured"):
        asyncio.run(tools.list_workspace_files())
    finally:
      config.WORKSPACE_ROOT.__value__ = original

  def test_selected_tools_includes_list_when_configured(self):
    original = self._with_workspace_root("/workspace")
    try:
      selected = tools._selected_tools(["list_workspace_files"])
      assert "list_workspace_files" in selected
    finally:
      config.WORKSPACE_ROOT.__value__ = original

  def test_selected_tools_omits_list_when_unconfigured(self):
    original = self._with_workspace_root("")
    try:
      selected = tools._selected_tools(["list_workspace_files"])
      assert "list_workspace_files" not in selected
    finally:
      config.WORKSPACE_ROOT.__value__ = original

  def _init_git_repo(self, root: Path) -> None:
    import subprocess

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

  def test_git_diff_workspace_returns_stat_and_name_only(self):
    import asyncio
    import subprocess

    with tempfile.TemporaryDirectory() as workspace:
      root = Path(workspace)
      self._init_git_repo(root)
      src = root / "src"
      src.mkdir()
      (src / "a.py").write_text("x = 1\n", encoding="utf-8")
      subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
      subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=root,
        check=True,
        capture_output=True,
      )
      (src / "a.py").write_text("x = 2\n", encoding="utf-8")

      original_root = self._with_workspace_root(workspace)
      try:
        result = asyncio.run(tools.git_diff_workspace())
      finally:
        config.WORKSPACE_ROOT.__value__ = original_root

    assert "<git_diff_name_only>" in result
    assert "src/a.py" in result
    assert "</git_diff_name_only>" in result
    assert "<git_diff_stat>" in result
    assert "</git_diff_stat>" in result

  def test_git_diff_workspace_scopes_path(self):
    import asyncio
    import subprocess
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as workspace:
      root = Path(workspace)
      self._init_git_repo(root)
      src = root / "src"
      other = root / "other"
      src.mkdir()
      other.mkdir()
      (src / "a.py").write_text("x = 1\n", encoding="utf-8")
      (other / "b.py").write_text("y = 1\n", encoding="utf-8")
      subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
      subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=root,
        check=True,
        capture_output=True,
      )
      (src / "a.py").write_text("x = 2\n", encoding="utf-8")
      (other / "b.py").write_text("y = 2\n", encoding="utf-8")

      original_root = self._with_workspace_root(workspace)
      try:
        with patch.object(tools, "run_git_diff", wraps=tools.run_git_diff) as mocked:
          result = asyncio.run(tools.git_diff_workspace(path="src"))
          assert mocked.call_args.kwargs["paths"] == ["src"]
      finally:
        config.WORKSPACE_ROOT.__value__ = original_root

    assert "src/a.py" in result
    assert "other/b.py" not in result

  def test_git_diff_workspace_path_jail(self):
    with tempfile.TemporaryDirectory() as workspace:
      root = Path(workspace)
      self._init_git_repo(root)
      original = self._with_workspace_root(workspace)
      try:
        with pytest.raises(ValueError, match="stay inside the workspace root"):
          tools._workspace_search_path("../outside")
      finally:
        config.WORKSPACE_ROOT.__value__ = original

  def test_git_diff_workspace_requires_git_repo(self):
    import asyncio

    with tempfile.TemporaryDirectory() as workspace:
      original = self._with_workspace_root(workspace)
      try:
        with pytest.raises(ValueError, match="not a git repository"):
          asyncio.run(tools.git_diff_workspace())
      finally:
        config.WORKSPACE_ROOT.__value__ = original

  def test_git_diff_workspace_requires_workspace_root(self):
    import asyncio

    original = self._with_workspace_root("")
    try:
      with pytest.raises(ValueError, match="Workspace root is not configured"):
        asyncio.run(tools.git_diff_workspace())
    finally:
      config.WORKSPACE_ROOT.__value__ = original

  def test_selected_tools_includes_git_diff_when_git_workspace(self):
    with tempfile.TemporaryDirectory() as workspace:
      root = Path(workspace)
      self._init_git_repo(root)
      original = self._with_workspace_root(workspace)
      try:
        selected = tools._selected_tools(["git_diff_workspace"])
        assert "git_diff_workspace" in selected
      finally:
        config.WORKSPACE_ROOT.__value__ = original

  def test_selected_tools_omits_git_diff_when_not_git_repo(self):
    with tempfile.TemporaryDirectory() as workspace:
      original = self._with_workspace_root(workspace)
      try:
        selected = tools._selected_tools(["git_diff_workspace"])
        assert "git_diff_workspace" not in selected
      finally:
        config.WORKSPACE_ROOT.__value__ = original

  def test_selected_tools_omits_git_diff_when_unconfigured(self):
    original = self._with_workspace_root("")
    try:
      selected = tools._selected_tools(["git_diff_workspace"])
      assert "git_diff_workspace" not in selected
    finally:
      config.WORKSPACE_ROOT.__value__ = original