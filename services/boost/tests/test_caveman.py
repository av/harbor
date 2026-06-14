"""Unit tests for the caveman Boost module."""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chat as ch
import config
from modules import caveman
from research.brief import RESEARCH_UNAVAILABLE_NOTE, ResearchBrief, render_to_system
from research.budget import BudgetExceeded, ResearchBudget


class TestCavemanHeuristics:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  def test_skips_acknowledgments(self):
    assert caveman.should_skip_research(self._chat("thanks!"))
    assert caveman.should_skip_research(self._chat("ok"))

  def test_skips_short_continue(self):
    assert caveman.should_skip_research(self._chat("continue"))

  def test_skips_coding_deliverable_without_research_signals(self):
    chat = self._chat("Please implement a retry helper in services/boost/src/utils.py")
    assert caveman.should_skip_research(chat)

  def test_does_not_skip_coding_deliverable_with_research_signals(self):
    chat = self._chat(
      "Implement OAuth against the latest Stripe API documentation for checkout sessions."
    )
    assert not caveman.should_skip_research(chat)

  def test_needs_research_when_module_prefix_used(self):
    chat = self._chat("Summarize how Harbor Boost modules are loaded.")
    llm = MagicMock(module=caveman.ID_PREFIX)
    assert caveman.needs_research(chat, llm)

  def test_skips_implementation_edit_even_with_module_prefix(self):
    chat = self._chat("Implement the helper in utils.py")
    llm = MagicMock(module=caveman.ID_PREFIX)
    assert not caveman.needs_research(chat, llm)

  def test_needs_research_false_for_ack_when_prefix_used(self):
    chat = self._chat("thanks")
    llm = MagicMock(module=caveman.ID_PREFIX)
    assert not caveman.needs_research(chat, llm)

  def test_research_heuristic_detects_questions(self):
    assert caveman.research_heuristic("What changed in Python 3.13 asyncio semantics?")

  def test_research_heuristic_rejects_short_messages(self):
    assert not caveman.research_heuristic("hi")


class TestCavemanQueryExtraction:
  @pytest.mark.asyncio
  async def test_extract_search_queries_dedupes_and_limits(self):
    chat = ch.Chat.from_conversation([{"role": "user", "content": "What is new in FastAPI?"}])
    llm = MagicMock()
    llm.url = "http://example.com"
    llm.headers = {}
    llm.query_params = {}
    llm.model = "test-model"

    with patch.object(caveman, "_cheap_llm") as cheap_llm:
      cheap = MagicMock()
      cheap.chat_completion = AsyncMock(
        return_value={
          "queries": [
            "FastAPI 2026 release notes",
            "fastapi 2026 release notes",
            "FastAPI breaking changes",
            "FastAPI migration guide",
            "ignored fifth query",
          ]
        }
      )
      cheap_llm.return_value = cheap

      queries = await caveman.extract_search_queries(chat, llm, "What is new in FastAPI?")

    assert queries == [
      "FastAPI 2026 release notes",
      "FastAPI breaking changes",
      "FastAPI migration guide",
    ]


class TestCavemanGatherResearch:
  @pytest.mark.asyncio
  async def test_gather_research_respects_search_budget(self):
    budget = ResearchBudget(max_searches=1, max_url_reads=0, max_chars=5000)

    with patch("modules.caveman.fetch.web_search", new=AsyncMock(return_value="1. [A](https://a.example) (Date: N/A)\nSnippet")):
      brief = await caveman.gather_research(["first query", "second query"], budget)

    assert budget.searches_used == 1
    assert len(brief.searches) >= 1
    assert any("budget exhausted" in note.lower() for note in brief.notes)

  @pytest.mark.asyncio
  async def test_gather_research_reads_top_hit_when_budget_allows(self):
    budget = ResearchBudget(max_searches=1, max_url_reads=1, max_chars=5000)
    search_text = "1. [Docs](https://docs.example.com) (Date: N/A)\nSnippet"

    with (
      patch("modules.caveman.fetch.web_search", new=AsyncMock(return_value=search_text)),
      patch("modules.caveman.fetch.read_url", new=AsyncMock(return_value="full page content")) as read_url,
    ):
      brief = await caveman.gather_research(["docs example"], budget)

    read_url.assert_awaited_once()
    assert read_url.await_args.args[0] == "https://docs.example.com"
    assert read_url.await_args.kwargs["max_chars"] <= 5000
    assert len(brief.pages) == 1
    assert brief.pages[0].snippet == "full page content"

  @pytest.mark.asyncio
  async def test_gather_research_handles_search_failure_messages(self):
    budget = ResearchBudget(max_searches=1, max_url_reads=0, max_chars=5000)
    llm = MagicMock()
    llm.emit_status = AsyncMock()

    with patch(
      "modules.caveman.fetch.web_search",
      new=AsyncMock(return_value="Web search failed: timeout"),
    ):
      brief = await caveman.gather_research(["docs example"], budget, llm)

    assert any("search failed" in note.lower() for note in brief.notes)
    assert RESEARCH_UNAVAILABLE_NOTE in brief.notes
    statuses = [call.args[0] for call in llm.emit_status.await_args_list]
    assert any("search unavailable" in status for status in statuses)

  @pytest.mark.asyncio
  async def test_gather_research_handles_read_failures(self):
    budget = ResearchBudget(max_searches=1, max_url_reads=1, max_chars=5000)
    search_text = "1. [Docs](https://docs.example.com) (Date: N/A)\nSnippet"

    with (
      patch("modules.caveman.fetch.web_search", new=AsyncMock(return_value=search_text)),
      patch("modules.caveman.fetch.read_url", new=AsyncMock(side_effect=ValueError("blocked"))),
    ):
      brief = await caveman.gather_research(["docs example"], budget)

    assert brief.pages == []
    assert any("Could not read" in note for note in brief.notes)


class TestCavemanApply:
  @pytest.mark.asyncio
  async def test_apply_passes_through_on_skip(self):
    chat = ch.Chat.from_conversation([{"role": "user", "content": "thanks"}])
    llm = MagicMock(module=caveman.ID_PREFIX)
    llm.stream_final_completion = AsyncMock()

    with patch.object(caveman, "extract_search_queries", new=AsyncMock()) as extract:
      await caveman.apply(chat, llm)

    extract.assert_not_called()
    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_apply_injects_brief_and_completes(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "What are the latest Harbor Boost module patterns?"},
    ])
    llm = MagicMock(module=caveman.ID_PREFIX)
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    brief = ResearchBrief(query="latest Harbor Boost module patterns")
    brief.add_search_results("harbor boost modules", "1. [Docs](https://example.com) (Date: N/A)\nsnippet")

    with (
      patch.object(caveman, "extract_search_queries", new=AsyncMock(return_value=["harbor boost modules"])),
      patch.object(caveman, "gather_research", new=AsyncMock(return_value=brief)),
    ):
      await caveman.apply(chat, llm)

    rendered = render_to_system(brief)
    assert rendered in chat.history()[0]["content"]
    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_apply_injects_research_unavailable_note_on_total_failure(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "What are the latest Harbor Boost module patterns?"},
    ])
    llm = MagicMock(module=caveman.ID_PREFIX)
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    brief = ResearchBrief(query="latest Harbor Boost module patterns")
    brief.add_note(RESEARCH_UNAVAILABLE_NOTE)

    with (
      patch.object(caveman, "extract_search_queries", new=AsyncMock(return_value=["harbor boost modules"])),
      patch.object(caveman, "gather_research", new=AsyncMock(return_value=brief)),
      patch.object(caveman.brief_mod, "has_usable_research", return_value=False),
    ):
      await caveman.apply(chat, llm)

    rendered = render_to_system(brief)
    assert RESEARCH_UNAVAILABLE_NOTE in rendered
    statuses = [call.args[0] for call in llm.emit_status.await_args_list]
    assert any("research unavailable" in status for status in statuses)
    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_apply_uses_config_budget(self):
    chat = ch.Chat.from_conversation([{"role": "user", "content": "What is new in FastAPI 2026?"}])
    llm = MagicMock(module=caveman.ID_PREFIX)
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    original = (
      config.CAVEMAN_MAX_SEARCHES.__value__,
      config.CAVEMAN_MAX_URL_READS.__value__,
      config.CAVEMAN_MAX_CHARS.__value__,
    )
    try:
      config.CAVEMAN_MAX_SEARCHES.__value__ = 4
      config.CAVEMAN_MAX_URL_READS.__value__ = 2
      config.CAVEMAN_MAX_CHARS.__value__ = 9000

      with (
        patch.object(caveman, "extract_search_queries", new=AsyncMock(return_value=["fastapi 2026"])),
        patch.object(caveman, "gather_research", new=AsyncMock(return_value=ResearchBrief())) as gather,
      ):
        await caveman.apply(chat, llm)

      budget = gather.await_args.args[1]
      assert budget.max_searches == 4
      assert budget.max_url_reads == 2
      assert budget.max_chars == 9000
    finally:
      (
        config.CAVEMAN_MAX_SEARCHES.__value__,
        config.CAVEMAN_MAX_URL_READS.__value__,
        config.CAVEMAN_MAX_CHARS.__value__,
      ) = original