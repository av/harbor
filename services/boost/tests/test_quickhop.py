"""Unit tests for the quickhop Boost module."""

import os
import sys
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chat as ch
import config
from modules import quickhop
from research.brief import RESEARCH_UNAVAILABLE_NOTE, ResearchBrief, render_to_system
from research.budget import BudgetExceeded, ResearchBudget
from state import request as request_state


@contextmanager
def request_context():
  req = MagicMock()
  req.state = type("State", (), {})()
  token_req = request_state.set(req)
  try:
    yield req
  finally:
    request_state.reset(token_req)
    if hasattr(req.state, quickhop.BRIEF_CACHE_KEY):
      delattr(req.state, quickhop.BRIEF_CACHE_KEY)


@pytest.fixture
def quickhop_trigger_mode():
  original = config.QUICKHOP_TRIGGER.__value__
  yield
  config.QUICKHOP_TRIGGER.__value__ = original


@pytest.fixture
def quickhop_cache_mode():
  original = config.QUICKHOP_CACHE_BRIEF.__value__
  yield
  config.QUICKHOP_CACHE_BRIEF.__value__ = original


class TestQuickhopHeuristics:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  def test_skips_acknowledgments(self):
    assert quickhop.research_skip_reason(self._chat("thanks!")) is not None
    assert quickhop.research_skip_reason(self._chat("ok")) is not None
    assert quickhop.research_skip_reason(self._chat("thanks for the help!")) is not None
    assert quickhop.research_skip_reason(self._chat("looks good, thanks")) is not None

  def test_skips_short_continue(self):
    assert quickhop.research_skip_reason(self._chat("continue")) is not None

  def test_skips_coding_deliverable_without_research_signals(self):
    chat = self._chat("Please implement a retry helper in services/boost/src/utils.py")
    assert quickhop.research_skip_reason(chat) is not None

  def test_does_not_skip_coding_deliverable_with_research_signals(self):
    chat = self._chat(
      "Implement OAuth against the latest Stripe API documentation for checkout sessions."
    )
    assert quickhop.research_skip_reason(chat) is None

  @pytest.mark.asyncio
  async def test_needs_research_when_module_prefix_used(self):
    chat = self._chat("Summarize how Harbor Boost modules are loaded.")
    llm = MagicMock(module=quickhop.ID_PREFIX)
    gate_reason, _ = await quickhop.research_gate_reason(chat, llm)
    assert gate_reason == "triggered"

  @pytest.mark.asyncio
  async def test_skips_implementation_edit_even_with_module_prefix(self):
    chat = self._chat("Implement the helper in utils.py")
    llm = MagicMock(module=quickhop.ID_PREFIX)
    gate_reason, _ = await quickhop.research_gate_reason(chat, llm)
    assert gate_reason != "triggered"

  @pytest.mark.asyncio
  async def test_needs_research_false_for_ack_when_prefix_used(self):
    chat = self._chat("thanks")
    llm = MagicMock(module=quickhop.ID_PREFIX)
    gate_reason, _ = await quickhop.research_gate_reason(chat, llm)
    assert gate_reason != "triggered"

  def test_research_heuristic_detects_questions(self):
    assert quickhop.research_heuristic("What changed in Python 3.13 asyncio semantics?")

  def test_research_heuristic_rejects_short_messages(self):
    assert not quickhop.research_heuristic("hi")

  def test_research_heuristic_rejects_bare_questions_without_research_signals(self):
    assert not quickhop.research_heuristic("How should I structure this function?")
    assert not quickhop.research_heuristic("Can you explain what went wrong here?")


class TestQuickhopLlmTrigger:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  @pytest.mark.asyncio
  async def test_llm_trigger_yes_runs_classifier(self, quickhop_trigger_mode):
    chat = self._chat("What changed in Python 3.13 asyncio semantics?")
    llm = MagicMock(module=None)
    config.QUICKHOP_TRIGGER.__value__ = "llm"

    with patch("research.orchestrate.cheap_llm") as cheap_llm:
      cheap = MagicMock()
      cheap.chat_completion = AsyncMock(
        return_value={"needs_external_research": True},
      )
      cheap_llm.return_value = cheap

      gate_reason, _ = await quickhop.research_gate_reason(chat, llm)
      assert gate_reason == "triggered"

    cheap.chat_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_llm_trigger_no_skips_research(self, quickhop_trigger_mode):
    chat = self._chat("Refactor the retry helper in services/boost/src/utils.py")
    llm = MagicMock(module=None)
    config.QUICKHOP_TRIGGER.__value__ = "llm"

    with patch("research.orchestrate.cheap_llm") as cheap_llm:
      cheap = MagicMock()
      cheap.chat_completion = AsyncMock(
        return_value={"needs_external_research": False},
      )
      cheap_llm.return_value = cheap

      gate_reason, _ = await quickhop.research_gate_reason(chat, llm)
      assert gate_reason != "triggered"

  @pytest.mark.asyncio
  async def test_llm_trigger_skips_classifier_with_module_prefix(self, quickhop_trigger_mode):
    chat = self._chat("Summarize how Harbor Boost modules are loaded.")
    llm = MagicMock(module=quickhop.ID_PREFIX)
    config.QUICKHOP_TRIGGER.__value__ = "llm"

    with patch("research.orchestrate.cheap_llm") as cheap_llm:
      gate_reason, _ = await quickhop.research_gate_reason(chat, llm)
      assert gate_reason == "triggered"

    cheap_llm.assert_not_called()

  @pytest.mark.asyncio
  async def test_llm_trigger_falls_back_to_heuristic_on_failure(self, quickhop_trigger_mode):
    chat = self._chat("What changed in Python 3.13 asyncio semantics?")
    llm = MagicMock(module=None)
    config.QUICKHOP_TRIGGER.__value__ = "llm"

    with patch("research.orchestrate.cheap_llm") as cheap_llm:
      cheap = MagicMock()
      cheap.chat_completion = AsyncMock(side_effect=RuntimeError("classifier down"))
      cheap_llm.return_value = cheap

      gate_reason, _ = await quickhop.research_gate_reason(chat, llm)
      assert gate_reason == "triggered"

  @pytest.mark.asyncio
  async def test_heuristic_mode_does_not_call_classifier(self, quickhop_trigger_mode):
    chat = self._chat("What changed in Python 3.13 asyncio semantics?")
    llm = MagicMock(module=None)
    config.QUICKHOP_TRIGGER.__value__ = "heuristic"

    with patch("research.orchestrate.cheap_llm") as cheap_llm:
      gate_reason, _ = await quickhop.research_gate_reason(chat, llm)
      assert gate_reason == "triggered"

    cheap_llm.assert_not_called()

  @pytest.mark.asyncio
  async def test_apply_llm_trigger_skips_when_classifier_says_no(self, quickhop_trigger_mode):
    chat = self._chat("Refactor the retry helper in services/boost/src/utils.py")
    llm = MagicMock(module=quickhop.ID_PREFIX)
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()
    config.QUICKHOP_TRIGGER.__value__ = "llm"

    with (
      patch("research.orchestrate.cheap_llm") as cheap_llm,
      patch.object(quickhop, "extract_search_queries", new=AsyncMock()) as extract,
    ):
      cheap = MagicMock()
      cheap.chat_completion = AsyncMock(
        return_value={"needs_external_research": False},
      )
      cheap_llm.return_value = cheap
      llm.module = None

      await quickhop.apply(chat, llm)

    extract.assert_not_called()
    llm.stream_final_completion.assert_awaited_once()


class TestQuickhopQueryQuality:
  def test_query_extraction_prompt_quotes_exact_error_strings(self):
    prompt = quickhop.QUERY_EXTRACTION_PROMPT

    assert "exact error string" in prompt
    assert "double quotes" in prompt
    assert "error message" in prompt or "stack trace" in prompt

  def test_query_extraction_prompt_includes_version_numbers(self):
    prompt = quickhop.QUERY_EXTRACTION_PROMPT

    assert "version numbers" in prompt
    assert "carry those" in prompt
    assert "versions into relevant queries" in prompt

  def test_query_extraction_prompt_prefers_official_docs(self):
    prompt = quickhop.QUERY_EXTRACTION_PROMPT

    assert "site:docs.*" in prompt
    assert "official documentation" in prompt.lower()
    assert "docs" in prompt


class TestQuickhopQueryExtraction:
  @pytest.mark.asyncio
  async def test_extract_search_queries_dedupes_and_limits(self):
    chat = ch.Chat.from_conversation([{"role": "user", "content": "What is new in FastAPI?"}])
    llm = MagicMock()
    llm.url = "http://example.com"
    llm.headers = {}
    llm.query_params = {}
    llm.model = "test-model"

    with patch("research.orchestrate.cheap_llm") as cheap_llm:
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

      queries = await quickhop.extract_search_queries(chat, llm, "What is new in FastAPI?")

    assert queries == [
      "FastAPI 2026 release notes",
      "FastAPI breaking changes",
      "FastAPI migration guide",
    ]

  @pytest.mark.asyncio
  async def test_extract_search_queries_uses_config_max_queries(self):
    chat = ch.Chat.from_conversation([{"role": "user", "content": "What is new in FastAPI?"}])
    llm = MagicMock()
    llm.url = "http://example.com"
    llm.headers = {}
    llm.query_params = {}
    llm.model = "test-model"

    original = config.QUICKHOP_MAX_QUERIES.__value__
    try:
      config.QUICKHOP_MAX_QUERIES.__value__ = 2

      with patch("research.orchestrate.cheap_llm") as cheap_llm:
        cheap = MagicMock()
        cheap.chat_completion = AsyncMock(
          return_value={
            "queries": [
              "FastAPI 2026 release notes",
              "FastAPI breaking changes",
              "FastAPI migration guide",
            ]
          }
        )
        cheap_llm.return_value = cheap

        queries = await quickhop.extract_search_queries(chat, llm, "What is new in FastAPI?")

      assert queries == [
        "FastAPI 2026 release notes",
        "FastAPI breaking changes",
      ]
    finally:
      config.QUICKHOP_MAX_QUERIES.__value__ = original


class TestQuickhopGatherResearch:
  @pytest.mark.asyncio
  async def test_gather_research_respects_search_budget(self):
    budget = ResearchBudget(max_searches=1, max_url_reads=0, max_chars=5000)

    with patch("research.fetch.web_search", new=AsyncMock(return_value="1. [A](https://a.example) (Date: N/A)\nSnippet")):
      brief = await quickhop.gather_research(["first query", "second query"], budget)

    assert budget.searches_used == 1
    assert len(brief.searches) >= 1
    assert any("budget exhausted" in note.lower() for note in brief.notes)

  @pytest.mark.asyncio
  async def test_gather_research_reads_top_hit_when_budget_allows(self):
    budget = ResearchBudget(max_searches=1, max_url_reads=1, max_chars=5000)
    search_text = "1. [Docs](https://docs.example.com) (Date: N/A)\nSnippet"

    with (
      patch("research.fetch.web_search", new=AsyncMock(return_value=search_text)),
      patch("research.fetch.read_url", new=AsyncMock(return_value="full page content")) as read_url,
    ):
      brief = await quickhop.gather_research(["docs example"], budget)

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
      "research.fetch.web_search",
      new=AsyncMock(return_value="Web search failed: timeout"),
    ):
      brief = await quickhop.gather_research(["docs example"], budget, llm)

    assert any("search failed" in note.lower() for note in brief.notes)
    assert RESEARCH_UNAVAILABLE_NOTE in brief.notes
    statuses = [call.args[0] for call in llm.emit_status.await_args_list]
    assert any("search unavailable" in status for status in statuses)

  @pytest.mark.asyncio
  async def test_gather_research_handles_read_failures(self):
    budget = ResearchBudget(max_searches=1, max_url_reads=1, max_chars=5000)
    search_text = "1. [Docs](https://docs.example.com) (Date: N/A)\nSnippet"

    with (
      patch("research.fetch.web_search", new=AsyncMock(return_value=search_text)),
      patch("research.fetch.read_url", new=AsyncMock(side_effect=ValueError("blocked"))),
    ):
      brief = await quickhop.gather_research(["docs example"], budget)

    assert brief.pages == []
    assert any("Could not read" in note for note in brief.notes)


class TestQuickhopBriefCache:
  def test_docs_note_cache_brief_is_experimental(self):
    assert "cache_brief" in quickhop.DOCS
    assert "experimental" in quickhop.DOCS.lower()

  def test_question_hash_ignores_surrounding_whitespace(self):
    message = "What changed in Python 3.13 asyncio semantics?"
    import research.brief_cache as brief_cache

    assert brief_cache.question_hash(message) == brief_cache.question_hash(f"  {message}  ")

  @pytest.mark.asyncio
  async def test_cache_disabled_runs_research_each_time(self, quickhop_cache_mode):
    config.QUICKHOP_CACHE_BRIEF.__value__ = False
    question = "What are the latest Harbor Boost module patterns?"
    brief = ResearchBrief(query="harbor boost modules")
    brief.facts = ["quickhop performs fast one-hop research"]

    with request_context():
      chat = ch.Chat.from_conversation([{"role": "user", "content": question}])
      llm = MagicMock(module=quickhop.ID_PREFIX)
      llm.emit_status = AsyncMock()
      llm.stream_final_completion = AsyncMock()

      with (
        patch.object(quickhop, "extract_search_queries", new=AsyncMock(return_value=["harbor boost modules"])) as extract,
        patch.object(quickhop, "gather_research", new=AsyncMock(return_value=brief)) as gather,
      ):
        await quickhop.apply(chat, llm)
        await quickhop.apply(chat, llm)

    assert extract.await_count == 2
    assert gather.await_count == 2

  @pytest.mark.asyncio
  async def test_cache_enabled_reuses_brief_for_same_question(self, quickhop_cache_mode):
    config.QUICKHOP_CACHE_BRIEF.__value__ = True
    question = "What are the latest Harbor Boost module patterns?"
    brief = ResearchBrief(query="harbor boost modules")
    brief.facts = ["quickhop performs fast one-hop research"]

    with request_context():
      chat = ch.Chat.from_conversation([{"role": "user", "content": question}])
      llm = MagicMock(module=quickhop.ID_PREFIX)
      llm.emit_status = AsyncMock()
      llm.stream_final_completion = AsyncMock()

      with (
        patch.object(quickhop, "extract_search_queries", new=AsyncMock(return_value=["harbor boost modules"])) as extract,
        patch.object(quickhop, "gather_research", new=AsyncMock(return_value=brief)) as gather,
      ):
        await quickhop.apply(chat, llm)
        await quickhop.apply(chat, llm)

    extract.assert_awaited_once()
    gather.assert_awaited_once()
    statuses = [call.args[0] for call in llm.emit_status.await_args_list]
    assert any("using cached brief" in status for status in statuses)

  @pytest.mark.asyncio
  async def test_cache_enabled_with_workflow_config_dict(self, quickhop_cache_mode):
    """Regression: workflow module config dict must not shadow QUICKHOP_CACHE_BRIEF."""
    config.QUICKHOP_CACHE_BRIEF.__value__ = True
    question = "What are the latest Harbor Boost module patterns?"
    brief = ResearchBrief(query="harbor boost modules")
    brief.facts = ["quickhop performs fast one-hop research"]
    workflow_cfg = {"defer_final": True}

    with request_context():
      chat = ch.Chat.from_conversation([{"role": "user", "content": question}])
      llm = MagicMock(module=quickhop.ID_PREFIX)
      llm.emit_status = AsyncMock()
      llm.stream_final_completion = AsyncMock()

      with (
        patch.object(quickhop, "extract_search_queries", new=AsyncMock(return_value=["harbor boost modules"])) as extract,
        patch.object(quickhop, "gather_research", new=AsyncMock(return_value=brief)) as gather,
      ):
        await quickhop.apply(chat, llm, workflow_cfg)
        await quickhop.apply(chat, llm, workflow_cfg)

    extract.assert_awaited_once()
    gather.assert_awaited_once()
    statuses = [call.args[0] for call in llm.emit_status.await_args_list]
    assert any("using cached brief" in status for status in statuses)
    llm.stream_final_completion.assert_not_called()

  @pytest.mark.asyncio
  async def test_cache_enabled_runs_research_for_different_question(self, quickhop_cache_mode):
    config.QUICKHOP_CACHE_BRIEF.__value__ = True
    first_question = "What are the latest Harbor Boost module patterns?"
    second_question = "What changed in Python 3.13 asyncio semantics?"
    first_brief = ResearchBrief(query="harbor boost modules")
    first_brief.facts = ["quickhop performs fast one-hop research"]
    second_brief = ResearchBrief(query="python 3.13 asyncio")
    second_brief.facts = ["asyncio task groups stabilized in 3.13"]

    with request_context():
      first_chat = ch.Chat.from_conversation([{"role": "user", "content": first_question}])
      second_chat = ch.Chat.from_conversation([{"role": "user", "content": second_question}])
      llm = MagicMock(module=quickhop.ID_PREFIX)
      llm.emit_status = AsyncMock()
      llm.stream_final_completion = AsyncMock()

      with (
        patch.object(
          quickhop,
          "extract_search_queries",
          new=AsyncMock(side_effect=[["harbor boost modules"], ["python 3.13 asyncio"]]),
        ) as extract,
        patch.object(
          quickhop,
          "gather_research",
          new=AsyncMock(side_effect=[first_brief, second_brief]),
        ) as gather,
      ):
        await quickhop.apply(first_chat, llm)
        await quickhop.apply(second_chat, llm)

    assert extract.await_count == 2
    assert gather.await_count == 2
    assert render_to_system(second_brief) in second_chat.history()[0]["content"]


class TestQuickhopStatusFormatting:
  def test_format_skipped_status_includes_gate_reason(self):
    assert quickhop.format_skipped_status("acknowledgment") == (
      "Quickhop research: skipped (acknowledgment)"
    )
    assert quickhop.format_skipped_status("implementation_turn") == (
      "Quickhop research: skipped (implementation_turn)"
    )

  def test_format_query_status_matches_deephop_style(self):
    assert quickhop.format_query_status(1) == "Quickhop research: (1 query)..."
    assert quickhop.format_query_status(3) == "Quickhop research: (3 queries)..."

  def test_format_gathered_status_includes_query_and_url_counts(self):
    assert quickhop.format_gathered_status(query_count=2, pages_read=1) == (
      "Quickhop research: 2 queries, read 1 URL..."
    )
    assert quickhop.format_gathered_status(query_count=1, pages_read=0) == (
      "Quickhop research: 1 query, read 0 URLs..."
    )


class TestQuickhopApply:
  @pytest.mark.asyncio
  async def test_apply_passes_through_on_skip(self):
    chat = ch.Chat.from_conversation([{"role": "user", "content": "thanks"}])
    llm = MagicMock(module=quickhop.ID_PREFIX)
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    with patch.object(quickhop, "extract_search_queries", new=AsyncMock()) as extract:
      await quickhop.apply(chat, llm)

    extract.assert_not_called()
    llm.emit_status.assert_awaited_once_with(
      "Quickhop research: skipped (acknowledgment)"
    )
    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_apply_passes_through_when_no_queries_extracted(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "What is the Stripe checkout session API response format in 2024?"},
    ])
    llm = MagicMock(module=quickhop.ID_PREFIX)
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    with (
      patch.object(quickhop, "extract_search_queries", new=AsyncMock(return_value=[])),
      patch.object(quickhop, "gather_research", new=AsyncMock()) as gather,
    ):
      await quickhop.apply(chat, llm)

    gather.assert_not_called()
    statuses = [call.args[0] for call in llm.emit_status.await_args_list]
    assert statuses == [
      "Quickhop research: planning queries...",
      "Quickhop research: skipped (no_queries_extracted)",
    ]
    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_apply_injects_brief_and_completes(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "What are the latest Harbor Boost module patterns?"},
    ])
    llm = MagicMock(module=quickhop.ID_PREFIX)
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    brief = ResearchBrief(query="latest Harbor Boost module patterns")
    brief.add_search_results("harbor boost modules", "1. [Docs](https://example.com) (Date: N/A)\nsnippet")

    with (
      patch.object(quickhop, "extract_search_queries", new=AsyncMock(return_value=["harbor boost modules"])),
      patch.object(quickhop, "gather_research", new=AsyncMock(return_value=brief)),
    ):
      await quickhop.apply(chat, llm)

    rendered = render_to_system(brief)
    assert rendered in chat.history()[0]["content"]
    statuses = [call.args[0] for call in llm.emit_status.await_args_list]
    assert "Quickhop research: planning queries..." in statuses
    assert "Quickhop research: (1 query)..." in statuses
    assert "Quickhop research: 1 query, read 0 URLs..." in statuses
    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_apply_injects_research_unavailable_note_on_total_failure(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "What are the latest Harbor Boost module patterns?"},
    ])
    llm = MagicMock(module=quickhop.ID_PREFIX)
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    brief = ResearchBrief(query="latest Harbor Boost module patterns")
    brief.add_note(RESEARCH_UNAVAILABLE_NOTE)

    with (
      patch.object(quickhop, "extract_search_queries", new=AsyncMock(return_value=["harbor boost modules"])),
      patch.object(quickhop, "gather_research", new=AsyncMock(return_value=brief)),
      patch.object(quickhop.brief_mod, "has_usable_research", return_value=False),
    ):
      await quickhop.apply(chat, llm)

    rendered = render_to_system(brief)
    assert RESEARCH_UNAVAILABLE_NOTE in rendered
    statuses = [call.args[0] for call in llm.emit_status.await_args_list]
    assert any("research unavailable" in status for status in statuses)
    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_apply_uses_config_budget(self):
    chat = ch.Chat.from_conversation([{"role": "user", "content": "What is new in FastAPI 2026?"}])
    llm = MagicMock(module=quickhop.ID_PREFIX)
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    original = (
      config.QUICKHOP_MAX_SEARCHES.__value__,
      config.QUICKHOP_MAX_URL_READS.__value__,
      config.QUICKHOP_MAX_CHARS.__value__,
    )
    try:
      config.QUICKHOP_MAX_SEARCHES.__value__ = 4
      config.QUICKHOP_MAX_URL_READS.__value__ = 2
      config.QUICKHOP_MAX_CHARS.__value__ = 9000

      with (
        patch.object(quickhop, "extract_search_queries", new=AsyncMock(return_value=["fastapi 2026"])),
        patch.object(quickhop, "gather_research", new=AsyncMock(return_value=ResearchBrief())) as gather,
      ):
        await quickhop.apply(chat, llm)

      budget = gather.await_args.args[1]
      assert budget.max_searches == 4
      assert budget.max_url_reads == 2
      assert budget.max_chars == 9000
    finally:
      (
        config.QUICKHOP_MAX_SEARCHES.__value__,
        config.QUICKHOP_MAX_URL_READS.__value__,
        config.QUICKHOP_MAX_CHARS.__value__,
      ) = original