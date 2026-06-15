"""Regression guards for research orchestration parallelism.

Not a benchmark suite — these tests mock slow fetches and assert that
``run_searches`` / ``read_urls`` complete faster in parallel than they
would sequentially.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import research.orchestrate as orchestrate
from research.brief import ResearchBrief
from research.budget import ResearchBudget

MOCK_FETCH_DELAY_S = 0.05


@pytest.fixture
def slow_search():
  async def _slow_search(query: str, *, max_results: int):
    await asyncio.sleep(MOCK_FETCH_DELAY_S)
    return f"1. [{query}](https://example.com/{query}) (Date: N/A)\nSnippet"

  return _slow_search


@pytest.fixture
def slow_read():
  async def _slow_read(url: str, *, max_chars: int):
    await asyncio.sleep(MOCK_FETCH_DELAY_S)
    return f"page body for {url}"

  return _slow_read


class TestResearchParallelRegression:
  @pytest.mark.asyncio
  async def test_run_searches_parallel_faster_than_sequential(self, slow_search):
    queries = ["q1", "q2", "q3", "q4"]
    budget = ResearchBudget(max_searches=4, max_url_reads=0, max_chars=20_000)
    sequential_sum = len(queries) * MOCK_FETCH_DELAY_S

    with patch("research.fetch.web_search", new=AsyncMock(side_effect=slow_search)):
      brief_seq = ResearchBrief()
      started = time.monotonic()
      await orchestrate.run_searches(
        queries,
        budget,
        brief_seq,
        module_id="benchmark",
        status_prefix="Research",
        parallel=False,
      )
      sequential_elapsed = time.monotonic() - started

      budget = ResearchBudget(max_searches=4, max_url_reads=0, max_chars=20_000)
      brief_par = ResearchBrief()
      started = time.monotonic()
      await orchestrate.run_searches(
        queries,
        budget,
        brief_par,
        module_id="benchmark",
        status_prefix="Research",
        parallel=True,
      )
      parallel_elapsed = time.monotonic() - started

    assert len(brief_seq.searches) == len(queries)
    assert len(brief_par.searches) == len(queries)
    assert sequential_elapsed >= sequential_sum * 0.9
    assert parallel_elapsed < sequential_sum
    assert parallel_elapsed < sequential_elapsed

  @pytest.mark.asyncio
  async def test_read_urls_parallel_faster_than_sequential(self, slow_read):
    urls = [f"https://example.com/{idx}" for idx in range(4)]
    budget = ResearchBudget(max_searches=0, max_url_reads=4, max_chars=20_000)
    sequential_sum = len(urls) * MOCK_FETCH_DELAY_S

    with patch("research.fetch.read_url", new=AsyncMock(side_effect=slow_read)):
      brief_seq = ResearchBrief()
      started = time.monotonic()
      await orchestrate.read_urls(
        urls,
        budget,
        brief_seq,
        module_id="benchmark",
        status_prefix="Research",
        parallel=False,
      )
      sequential_elapsed = time.monotonic() - started

      budget = ResearchBudget(max_searches=0, max_url_reads=4, max_chars=20_000)
      brief_par = ResearchBrief()
      started = time.monotonic()
      await orchestrate.read_urls(
        urls,
        budget,
        brief_par,
        module_id="benchmark",
        status_prefix="Research",
        parallel=True,
      )
      parallel_elapsed = time.monotonic() - started

    assert len(brief_seq.pages) == len(urls)
    assert len(brief_par.pages) == len(urls)
    assert sequential_elapsed >= sequential_sum * 0.9
    assert parallel_elapsed < sequential_sum
    assert parallel_elapsed < sequential_elapsed

  @pytest.mark.asyncio
  async def test_parallel_status_emitted_for_multi_item_batches(self, slow_search, slow_read):
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    budget = ResearchBudget(max_searches=2, max_url_reads=2, max_chars=20_000)

    with (
      patch("research.fetch.web_search", new=AsyncMock(side_effect=slow_search)),
      patch("research.fetch.read_url", new=AsyncMock(side_effect=slow_read)),
    ):
      await orchestrate.run_searches(
        ["alpha", "beta"],
        budget,
        ResearchBrief(),
        module_id="benchmark",
        status_prefix="Research",
        llm=llm,
      )
      await orchestrate.read_urls(
        ["https://a.example", "https://b.example"],
        budget,
        ResearchBrief(),
        module_id="benchmark",
        status_prefix="Research",
        llm=llm,
      )

    statuses = [call.args[0] for call in llm.emit_status.await_args_list]
    assert any("parallel" in status.lower() for status in statuses)