"""Unit tests for shared agentic module infrastructure."""

import os
import sys
import tempfile
from pathlib import Path
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chat as ch
import config
import deliverable
from research.brief import ResearchBrief, render_to_system
from research.budget import BudgetExceeded, ResearchBudget, budget_from_config
from research.fetch import require_http_url, trim
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