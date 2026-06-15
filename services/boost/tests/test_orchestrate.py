"""Performance and concurrency tests for research orchestration."""

import asyncio
import logging
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config
import research.orchestrate as orchestrate
from modules import ponytail
from research.brief import ResearchBrief
from research.budget import ResearchBudget


class TestOrchestrateParallelFetch:
  @pytest.mark.asyncio
  async def test_run_searches_parallelizes_with_concurrency_cap(self):
    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def slow_search(query: str, *, max_results: int):
      nonlocal active, peak
      async with lock:
        active += 1
        peak = max(peak, active)
      await asyncio.sleep(0.05)
      async with lock:
        active -= 1
      return f"1. [{query}](https://example.com/{query}) (Date: N/A)\nSnippet"

    budget = ResearchBudget(max_searches=4, max_url_reads=0, max_chars=20_000)
    brief = ResearchBrief()
    llm = MagicMock()
    llm.emit_status = AsyncMock()

    from unittest.mock import patch

    with patch("research.fetch.web_search", new=AsyncMock(side_effect=slow_search)):
      started = time.monotonic()
      await orchestrate.run_searches(
        ["q1", "q2", "q3", "q4"],
        budget,
        brief,
        module_id="ponytail",
        status_prefix="Ponytail research",
        phase="Ponytail hop 1",
        llm=llm,
      )
      elapsed = time.monotonic() - started

    assert budget.searches_used == 4
    assert len(brief.searches) == 4
    assert peak <= orchestrate.SEARCH_CONCURRENCY
    assert elapsed < 0.16
    statuses = [call.args[0] for call in llm.emit_status.await_args_list]
    assert any("up to 2 parallel" in status for status in statuses)

  @pytest.mark.asyncio
  async def test_read_urls_parallelizes_with_concurrency_cap(self):
    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def slow_read(url: str, *, max_chars: int):
      nonlocal active, peak
      async with lock:
        active += 1
        peak = max(peak, active)
      await asyncio.sleep(0.05)
      async with lock:
        active -= 1
      return f"page body for {url}"

    budget = ResearchBudget(max_searches=0, max_url_reads=4, max_chars=20_000)
    brief = ResearchBrief()
    llm = MagicMock()
    llm.emit_status = AsyncMock()

    from unittest.mock import patch

    with patch("research.fetch.read_url", new=AsyncMock(side_effect=slow_read)):
      started = time.monotonic()
      await orchestrate.read_urls(
        [f"https://example.com/{idx}" for idx in range(4)],
        budget,
        brief,
        module_id="ponytail",
        status_prefix="Ponytail research",
        phase="Ponytail hop 1",
        llm=llm,
      )
      elapsed = time.monotonic() - started

    assert budget.url_reads_used == 4
    assert len(brief.pages) == 4
    assert peak <= orchestrate.URL_READ_CONCURRENCY
    assert elapsed < 0.11
    statuses = [call.args[0] for call in llm.emit_status.await_args_list]
    assert any("up to 3 parallel" in status for status in statuses)

  @pytest.mark.asyncio
  async def test_run_searches_respects_budget_under_parallelism(self):
    from unittest.mock import patch

    budget = ResearchBudget(max_searches=1, max_url_reads=0, max_chars=5000)
    brief = ResearchBrief()

    with patch(
      "research.fetch.web_search",
      new=AsyncMock(return_value="1. [Docs](https://a.example) (Date: N/A)\nSnippet"),
    ) as web_search:
      await orchestrate.run_searches(
        ["api v1 docs", "api v2 docs", "api migration guide"],
        budget,
        brief,
        module_id=ponytail.ID_PREFIX,
        status_prefix="Ponytail research",
        phase="Ponytail hop 1",
      )

    assert web_search.await_count == 1
    assert budget.searches_used == 1
    assert any(
      "hop 1: search budget exhausted" in note.lower()
      for note in brief.notes
    )

  @pytest.mark.asyncio
  async def test_run_searches_deduplicates_identical_queries(self, caplog):
    from unittest.mock import patch

    budget = ResearchBudget(max_searches=4, max_url_reads=0, max_chars=20_000)
    brief = ResearchBrief()
    llm = MagicMock()
    llm.emit_status = AsyncMock()

    with patch(
      "research.fetch.web_search",
      new=AsyncMock(return_value="1. [Docs](https://a.example) (Date: N/A)\nSnippet"),
    ) as web_search:
      orchestrate.logger.propagate = True
      try:
        with caplog.at_level(logging.DEBUG, logger="research.orchestrate"):
          await orchestrate.run_searches(
            ["api docs", "API docs", "other query", "api docs"],
            budget,
            brief,
            module_id="ponytail",
            status_prefix="Ponytail research",
            phase="Ponytail hop 1",
            llm=llm,
          )
      finally:
        orchestrate.logger.propagate = False

    assert web_search.await_count == 2
    assert budget.searches_used == 2
    assert len(brief.searches) == 2
    assert any(
      "deduplicated 2 identical search queries (4 -> 2)" in record.message.lower()
      for record in caplog.records
    )


class TestOrchestrateBriefHelpers:
  def test_content_chars_in_brief_sums_search_and_page_snippets(self):
    brief = ResearchBrief()
    brief.add_search_results("query", "1. [Docs](https://a.example) (Date: N/A)\n12345")
    brief.add_page("https://b.example", "abcdef")

    assert orchestrate.content_chars_in_brief(brief) == len("12345") + len("abcdef")


class TestPonytailEarlyExit:
  @pytest.mark.asyncio
  async def test_run_research_loop_skips_second_hop_on_early_exit(self):
    import chat as ch
    from unittest.mock import patch

    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Migrate from FastAPI 0.100 to 0.115"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    budget = ResearchBudget(max_searches=4, max_url_reads=2, max_chars=50_000)

    search_text = "1. [Docs](https://docs.example.com) (Date: N/A)\n" + ("x" * 8000)
    gap = ponytail.GapAnalysis(
      gaps=["Need explicit deprecation list"],
      follow_up_queries=["FastAPI 0.115 deprecations"],
    )

    original = config.PONYTAIL_EARLY_EXIT_CHARS.__value__
    try:
      config.PONYTAIL_EARLY_EXIT_CHARS.__value__ = 10_000

      with (
        patch("research.fetch.web_search", new=AsyncMock(return_value=search_text)) as web_search,
        patch("research.fetch.read_url", new=AsyncMock(return_value="y" * 5000)) as read_url,
        patch.object(ponytail, "detect_gaps", new=AsyncMock(return_value=gap)) as detect_gaps,
        patch.object(
          ponytail,
          "synthesize_brief",
          new=AsyncMock(side_effect=lambda _c, _l, _m, brief: brief),
        ),
      ):
        brief, _ = await ponytail.run_research_loop(
          chat,
          llm,
          "Migrate from FastAPI 0.100 to 0.115",
          ["fastapi migration", "fastapi 0.115 changelog"],
          budget,
        )

    finally:
      config.PONYTAIL_EARLY_EXIT_CHARS.__value__ = original

    assert web_search.await_count == 2
    read_url.assert_awaited()
    detect_gaps.assert_not_called()
    assert any("early exit" in note.lower() for note in brief.notes)
    statuses = [call.args[0] for call in llm.emit_status.await_args_list]
    assert any("skipping hop 2" in status for status in statuses)