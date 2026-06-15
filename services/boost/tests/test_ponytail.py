"""Unit tests for the ponytail Boost module."""

import os
import sys
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chat as ch
import config
from modules import ponytail
from research.brief import RESEARCH_UNAVAILABLE_NOTE, ResearchBrief, render_to_system
from research.budget import ResearchBudget
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
    if hasattr(req.state, ponytail.BRIEF_CACHE_KEY):
      delattr(req.state, ponytail.BRIEF_CACHE_KEY)


def web_search_hop2_queries(searched: list[str], follow_up: list[str]) -> bool:
  """Return True when every follow-up query appears in the search call list."""
  return all(query in searched for query in follow_up)


class TestPonytailBriefSynthesis:
  def test_synthesis_prompt_requires_scannable_agent_format(self):
    prompt = ponytail.SYNTHESIS_PROMPT

    assert "scannable brief" in prompt
    assert "max ~12 words" in prompt
    assert "backticks" in prompt
    assert "Do not assume" in prompt
    assert "verification" in prompt.lower()

  def test_structured_brief_schema_describes_actionable_fields(self):
    schema = ponytail.StructuredBrief.model_json_schema()["properties"]

    assert "backticks" in schema["facts"]["description"]
    assert "Verify" in schema["uncertainties"]["description"]
    assert "Do not assume" in schema["do_not_assume"]["description"]
    assert "imperative" in schema["recommendation"]["description"].lower()

  @pytest.mark.asyncio
  async def test_synthesize_brief_truncates_oversized_research_summary(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Migrate from Django 4.2 to 5.0"},
    ])
    llm = MagicMock()
    brief = ResearchBrief(query="Migrate from Django 4.2 to 5.0")
    brief.add_page("https://example.com", "x" * 20_000)
    structured = {
      "facts": ["Django 5.0 removes django.utils.six"],
      "uncertainties": [],
      "recommendation": "Read the official migration guide first.",
      "do_not_assume": ["Do not assume Django 4.2 settings still work unchanged."],
    }

    original = config.PONYTAIL_SYNTHESIS_MAX_CHARS.__value__
    try:
      config.PONYTAIL_SYNTHESIS_MAX_CHARS.__value__ = 8000

      with patch("research.orchestrate.cheap_llm") as cheap_llm:
        cheap = MagicMock()
        cheap.chat_completion = AsyncMock(return_value=structured)
        cheap_llm.return_value = cheap

        result = await ponytail.synthesize_brief(
          chat, llm, "Migrate from Django 4.2 to 5.0", brief
        )

      kwargs = cheap.chat_completion.await_args.kwargs
      assert "[truncated to 8000 characters]" in kwargs["research_summary"]
      assert result.facts == structured["facts"]
      assert result.recommendation == structured["recommendation"]
    finally:
      config.PONYTAIL_SYNTHESIS_MAX_CHARS.__value__ = original


@pytest.fixture
def ponytail_trigger_mode():
  original = config.PONYTAIL_TRIGGER.__value__
  yield
  config.PONYTAIL_TRIGGER.__value__ = original


@pytest.fixture
def ponytail_cache_mode():
  original = config.PONYTAIL_CACHE_BRIEF.__value__
  yield
  config.PONYTAIL_CACHE_BRIEF.__value__ = original


class TestPonytailHeuristics:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  def test_skips_acknowledgments(self):
    assert ponytail.should_skip_research(self._chat("thanks!"))
    assert ponytail.should_skip_research(self._chat("ok"))

  def test_detects_research_heavy_migration(self):
    assert ponytail.is_research_heavy(
      "How do I migrate from FastAPI 0.100 to 0.115 without breaking dependencies?"
    )

  def test_detects_research_heavy_version_comparison(self):
    assert ponytail.is_research_heavy("Compare Python 3.12 vs 3.13 asyncio API behavior")

  def test_detects_research_heavy_api_behavior(self):
    assert ponytail.is_research_heavy(
      "What is the Stripe checkout session API endpoint response format?"
    )

  def test_rejects_generic_explanation(self):
    assert not ponytail.is_research_heavy("Explain what asyncio.gather does in plain English.")

  @pytest.mark.asyncio
  async def test_needs_research_for_migration_with_module_prefix(self):
    chat = self._chat("Plan a migration from Django 4.2 to 5.0 for our auth layer.")
    llm = MagicMock(module=ponytail.ID_PREFIX)
    assert await ponytail.needs_research(chat, llm)

  @pytest.mark.asyncio
  async def test_skips_implementation_without_research_signals_even_with_prefix(self):
    chat = self._chat("Implement the helper in utils.py")
    llm = MagicMock(module=ponytail.ID_PREFIX)
    assert not await ponytail.needs_research(chat, llm)

  @pytest.mark.asyncio
  async def test_needs_research_without_prefix_only_for_research_heavy(self):
    chat = self._chat("Summarize how Harbor Boost modules are loaded.")
    llm = MagicMock(module=None)
    assert not await ponytail.needs_research(chat, llm)

  @pytest.mark.asyncio
  async def test_needs_research_without_prefix_for_version_compare(self):
    chat = self._chat("Compare React 18 vs 19 migration breaking changes")
    llm = MagicMock(module=None)
    assert await ponytail.needs_research(chat, llm)


class TestPonytailLlmTrigger:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  @pytest.mark.asyncio
  async def test_llm_trigger_yes_runs_classifier(self, ponytail_trigger_mode):
    chat = self._chat("Compare Python 3.12 vs 3.13 asyncio API behavior")
    llm = MagicMock(module=None)
    config.PONYTAIL_TRIGGER.__value__ = "llm"

    with patch("research.orchestrate.cheap_llm") as cheap_llm:
      cheap = MagicMock()
      cheap.chat_completion = AsyncMock(
        return_value={"needs_deep_research": True},
      )
      cheap_llm.return_value = cheap

      assert await ponytail.needs_research(chat, llm)

    cheap.chat_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_llm_trigger_no_skips_research(self, ponytail_trigger_mode):
    chat = self._chat("Refactor the retry helper in services/boost/src/utils.py")
    llm = MagicMock(module=None)
    config.PONYTAIL_TRIGGER.__value__ = "llm"

    with patch("research.orchestrate.cheap_llm") as cheap_llm:
      cheap = MagicMock()
      cheap.chat_completion = AsyncMock(
        return_value={"needs_deep_research": False},
      )
      cheap_llm.return_value = cheap

      assert not await ponytail.needs_research(chat, llm)

  @pytest.mark.asyncio
  async def test_llm_trigger_skips_classifier_with_module_prefix(self, ponytail_trigger_mode):
    chat = self._chat("Plan a migration from Django 4.2 to 5.0 for our auth layer.")
    llm = MagicMock(module=ponytail.ID_PREFIX)
    config.PONYTAIL_TRIGGER.__value__ = "llm"

    with patch("research.orchestrate.cheap_llm") as cheap_llm:
      assert await ponytail.needs_research(chat, llm)

    cheap_llm.assert_not_called()

  @pytest.mark.asyncio
  async def test_llm_trigger_falls_back_to_heuristic_on_failure(self, ponytail_trigger_mode):
    chat = self._chat("Compare Python 3.12 vs 3.13 asyncio API behavior")
    llm = MagicMock(module=None)
    config.PONYTAIL_TRIGGER.__value__ = "llm"

    with patch("research.orchestrate.cheap_llm") as cheap_llm:
      cheap = MagicMock()
      cheap.chat_completion = AsyncMock(side_effect=RuntimeError("classifier down"))
      cheap_llm.return_value = cheap

      assert await ponytail.needs_research(chat, llm)

  @pytest.mark.asyncio
  async def test_heuristic_mode_does_not_call_classifier(self, ponytail_trigger_mode):
    chat = self._chat("Compare Python 3.12 vs 3.13 asyncio API behavior")
    llm = MagicMock(module=None)
    config.PONYTAIL_TRIGGER.__value__ = "heuristic"

    with patch("research.orchestrate.cheap_llm") as cheap_llm:
      assert await ponytail.needs_research(chat, llm)

    cheap_llm.assert_not_called()

  @pytest.mark.asyncio
  async def test_apply_llm_trigger_skips_when_classifier_says_no(self, ponytail_trigger_mode):
    chat = self._chat("Refactor the retry helper in services/boost/src/utils.py")
    llm = MagicMock(module=ponytail.ID_PREFIX)
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()
    config.PONYTAIL_TRIGGER.__value__ = "llm"

    with (
      patch("research.orchestrate.cheap_llm") as cheap_llm,
      patch.object(ponytail, "plan_search_queries", new=AsyncMock()) as plan,
    ):
      cheap = MagicMock()
      cheap.chat_completion = AsyncMock(
        return_value={"needs_deep_research": False},
      )
      cheap_llm.return_value = cheap
      llm.module = None

      await ponytail.apply(chat, llm)

    plan.assert_not_called()
    llm.emit_status.assert_awaited_once_with(
      "Ponytail research: skipped (llm_classifier_no)"
    )
    llm.stream_final_completion.assert_awaited_once()


class TestPonytailQueryPlanning:
  @pytest.mark.asyncio
  async def test_plan_search_queries_dedupes_and_limits(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Migrate from Pydantic v1 to v2"},
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
          "queries": [
            "Pydantic v2 migration guide",
            "pydantic v2 migration guide",
            "Pydantic v1 to v2 breaking changes",
            "Pydantic v2 validator changes",
            "Pydantic v2 config migration",
            "ignored sixth query",
          ]
        }
      )
      cheap_llm.return_value = cheap

      queries = await ponytail.plan_search_queries(
        chat, llm, "Migrate from Pydantic v1 to v2"
      )

    assert queries == [
      "Pydantic v2 migration guide",
      "Pydantic v1 to v2 breaking changes",
      "Pydantic v2 validator changes",
      "Pydantic v2 config migration",
      "ignored sixth query",
    ]

  @pytest.mark.asyncio
  async def test_plan_search_queries_uses_config_max_queries(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Migrate from Pydantic v1 to v2"},
    ])
    llm = MagicMock()
    llm.url = "http://example.com"
    llm.headers = {}
    llm.query_params = {}
    llm.model = "test-model"

    original = config.PONYTAIL_MAX_QUERIES.__value__
    try:
      config.PONYTAIL_MAX_QUERIES.__value__ = 2

      with patch("research.orchestrate.cheap_llm") as cheap_llm:
        cheap = MagicMock()
        cheap.chat_completion = AsyncMock(
          return_value={
            "queries": [
              "Pydantic v2 migration guide",
              "Pydantic v1 to v2 breaking changes",
              "Pydantic v2 validator changes",
            ]
          }
        )
        cheap_llm.return_value = cheap

        queries = await ponytail.plan_search_queries(
          chat, llm, "Migrate from Pydantic v1 to v2"
        )

      assert queries == [
        "Pydantic v2 migration guide",
        "Pydantic v1 to v2 breaking changes",
      ]
    finally:
      config.PONYTAIL_MAX_QUERIES.__value__ = original


class TestPonytailGapDetection:
  def _sparse_hop1_brief(self, query: str) -> ResearchBrief:
    """Hop-1 brief with general migration notes but no target version specifics."""
    brief = ResearchBrief(query=query)
    brief.add_search_results(
      "django migration overview",
      "1. [Guide](https://docs.djangoproject.com) (Date: N/A)\n"
      "General upgrade tips without explicit 5.0 release notes.",
    )
    brief.add_page(
      "https://docs.djangoproject.com",
      "Describes migration steps but omits Django 5.0 breaking changes.",
    )
    return brief

  @pytest.mark.asyncio
  async def test_detect_gaps_returns_follow_up_queries_from_llm(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Migrate from Django 4.2 to 5.0"},
    ])
    llm = MagicMock()
    brief = self._sparse_hop1_brief("Migrate from Django 4.2 to 5.0")
    gap_payload = {
      "gaps": [
        "No explicit Django 5.0 release notes cited",
        "Target version compatibility matrix missing",
      ],
      "follow_up_queries": [
        "Django 5.0 release notes breaking changes",
        "Django 4.2 to 5.0 migration guide official",
        "django 5.0 release notes breaking changes",
      ],
    }

    with patch("research.orchestrate.cheap_llm") as cheap_llm:
      cheap = MagicMock()
      cheap.chat_completion = AsyncMock(return_value=gap_payload)
      cheap_llm.return_value = cheap

      gap = await ponytail.detect_gaps(
        chat, llm, "Migrate from Django 4.2 to 5.0", brief
      )

    assert gap.gaps == gap_payload["gaps"]
    assert gap.follow_up_queries == gap_payload["follow_up_queries"]
    cheap.chat_completion.assert_awaited_once()
    kwargs = cheap.chat_completion.await_args.kwargs
    assert kwargs["schema"] is ponytail.GapAnalysis
    assert kwargs["prompt"] == ponytail.GAP_DETECTION_PROMPT
    assert kwargs["message"] == "Migrate from Django 4.2 to 5.0"
    assert "General upgrade tips" in kwargs["research_summary"]
    assert "omits Django 5.0 breaking changes" in kwargs["research_summary"]

  @pytest.mark.asyncio
  async def test_detect_gaps_returns_empty_when_llm_response_not_dict(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Compare API v1 vs v2"},
    ])
    llm = MagicMock()
    brief = ResearchBrief(query="Compare API v1 vs v2")

    with patch("research.orchestrate.cheap_llm") as cheap_llm:
      cheap = MagicMock()
      cheap.chat_completion = AsyncMock(return_value=None)
      cheap_llm.return_value = cheap

      gap = await ponytail.detect_gaps(chat, llm, "Compare API v1 vs v2", brief)

    assert gap.gaps == []
    assert gap.follow_up_queries == []

  @pytest.mark.asyncio
  async def test_run_research_loop_triggers_hop2_for_missing_version_info(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Migrate from Django 4.2 to 5.0"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    budget = ResearchBudget(max_searches=4, max_url_reads=2, max_chars=8000)

    hop1_search = (
      "1. [Guide](https://docs.djangoproject.com) (Date: N/A)\n"
      "General upgrade tips without explicit 5.0 release notes."
    )
    hop2_search = (
      "1. [Release notes](https://docs.djangoproject.com/en/5.0/releases/5.0/) "
      "(Date: N/A)\nDjango 5.0 removes django.utils.six."
    )
    gap = ponytail.GapAnalysis(
      gaps=[
        "No explicit Django 5.0 release notes cited",
        "Target version compatibility matrix missing",
      ],
      follow_up_queries=[
        "Django 5.0 release notes breaking changes",
        "Django 4.2 to 5.0 migration guide official",
      ],
    )

    searched_queries: list[str] = []

    async def track_search(query: str, **kwargs):
      searched_queries.append(query)
      return hop2_search if len(searched_queries) > 2 else hop1_search

    original = config.PONYTAIL_EARLY_EXIT_CHARS.__value__
    try:
      config.PONYTAIL_EARLY_EXIT_CHARS.__value__ = 15_000

      with (
        patch("research.fetch.web_search", new=AsyncMock(side_effect=track_search)),
        patch(
          "research.fetch.read_url",
          new=AsyncMock(return_value="Sparse page without version changelog."),
        ),
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
          "Migrate from Django 4.2 to 5.0",
          ["django migration overview", "django upgrade guide"],
          budget,
        )
    finally:
      config.PONYTAIL_EARLY_EXIT_CHARS.__value__ = original

    detect_gaps.assert_awaited_once()
    assert web_search_hop2_queries(searched_queries, gap.follow_up_queries)
    assert budget.searches_used == 4
    assert any("Gap: No explicit Django 5.0 release notes cited" in note for note in brief.notes)
    statuses = [call.args[0] for call in llm.emit_status.await_args_list]
    assert any("detecting gaps" in status for status in statuses)
    assert any("hop 2 (2 queries)" in status for status in statuses)
    assert any("hop 2, 2 queries, read" in status for status in statuses)

  @pytest.mark.asyncio
  async def test_run_research_loop_skips_hop2_on_early_exit(self):
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
        patch("research.fetch.read_url", new=AsyncMock(return_value="y" * 5000)),
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
    detect_gaps.assert_not_called()
    assert any("early exit" in note.lower() for note in brief.notes)
    statuses = [call.args[0] for call in llm.emit_status.await_args_list]
    assert any("early exit" in status for status in statuses)
    assert any("skipping hop 2" in status for status in statuses)
    assert not any("hop 2 (" in status for status in statuses)

  @pytest.mark.asyncio
  async def test_run_research_loop_skips_hop2_when_gap_has_no_follow_up_queries(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Compare Stripe API 2023-10-16 vs 2024-06-20"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    budget = ResearchBudget(max_searches=4, max_url_reads=2, max_chars=8000)
    gap = ponytail.GapAnalysis(
      gaps=["Minor wording differences only"],
      follow_up_queries=[],
    )

    with (
      patch("research.fetch.web_search", new=AsyncMock(return_value="1. [Docs](https://stripe.example) (Date: N/A)\nSnippet")) as web_search,
      patch("research.fetch.read_url", new=AsyncMock(return_value="stripe changelog")),
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
        "Compare Stripe API 2023-10-16 vs 2024-06-20",
        ["stripe api 2024-06-20 changelog", "stripe api migration"],
        budget,
      )

    detect_gaps.assert_awaited_once()
    assert web_search.await_count == 2
    statuses = [call.args[0] for call in llm.emit_status.await_args_list]
    assert not any("hop 2 (" in status for status in statuses)
    assert any("hop 1, 2 queries, read" in status for status in statuses)
    assert any("Gap: Minor wording differences only" in note for note in brief.notes)


class TestPonytailResearchLoop:
  @pytest.mark.asyncio
  async def test_run_research_loop_executes_two_hops(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Migrate from FastAPI 0.100 to 0.115"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    budget = ResearchBudget(max_searches=4, max_url_reads=2, max_chars=8000)

    search_text = "1. [Docs](https://docs.example.com) (Date: N/A)\nSnippet"
    gap = ponytail.GapAnalysis(
      gaps=["Need explicit deprecation list"],
      follow_up_queries=["FastAPI 0.115 deprecations"],
    )
    structured = ponytail.StructuredBrief(
      facts=["FastAPI 0.115 removes legacy routing hooks"],
      uncertainties=["Exact timeline for middleware changes"],
      recommendation="Pin FastAPI and run the official migration checklist.",
      do_not_assume=["That all plugins support 0.115"],
    )

    with (
      patch("research.fetch.web_search", new=AsyncMock(return_value=search_text)) as web_search,
      patch("research.fetch.read_url", new=AsyncMock(return_value="full page content")) as read_url,
      patch.object(ponytail, "detect_gaps", new=AsyncMock(return_value=gap)),
      patch.object(ponytail, "synthesize_brief", new=AsyncMock(side_effect=lambda _c, _l, _m, brief: (
        brief.__class__(
          query=brief.query,
          searches=brief.searches,
          pages=brief.pages,
          notes=brief.notes,
          facts=structured.facts,
          uncertainties=structured.uncertainties,
          recommendation=structured.recommendation,
          do_not_assume=structured.do_not_assume,
        )
      ))),
    ):
      brief, _ = await ponytail.run_research_loop(
        chat,
        llm,
        "Migrate from FastAPI 0.100 to 0.115",
        ["fastapi migration", "fastapi 0.115 changelog"],
        budget,
      )

    assert web_search.await_count == 3
    read_url.assert_awaited()
    assert brief.facts == structured.facts
    assert brief.recommendation == structured.recommendation
    assert brief.do_not_assume == structured.do_not_assume
    assert any("Gap:" in note for note in brief.notes)

  @pytest.mark.asyncio
  async def test_run_research_loop_skips_second_hop_when_budget_exhausted(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Compare API v1 vs v2 behavior"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    budget = ResearchBudget(max_searches=1, max_url_reads=0, max_chars=5000)
    gap = ponytail.GapAnalysis(
      gaps=["Need response schema diff"],
      follow_up_queries=["API v2 response schema changes"],
    )

    with (
      patch("research.fetch.web_search", new=AsyncMock(return_value="1. [Docs](https://a.example) (Date: N/A)\nSnippet")),
      patch.object(ponytail, "detect_gaps", new=AsyncMock(return_value=gap)),
      patch.object(ponytail, "synthesize_brief", new=AsyncMock(side_effect=lambda _c, _l, _m, brief: brief)),
    ):
      brief, _ = await ponytail.run_research_loop(
        chat,
        llm,
        "Compare API v1 vs v2 behavior",
        ["api v1 docs", "api v2 docs"],
        budget,
      )

    assert budget.searches_used == 1
    assert any("second research hop skipped" in note.lower() for note in brief.notes)


class TestPonytailBriefCache:
  def test_docs_note_cache_brief_is_experimental(self):
    assert "cache_brief" in ponytail.DOCS
    assert "experimental" in ponytail.DOCS.lower()

  def test_question_hash_ignores_surrounding_whitespace(self):
    message = "Compare Python 3.12 vs 3.13 asyncio API behavior"
    import research.brief_cache as brief_cache

    assert brief_cache.question_hash(message) == brief_cache.question_hash(f"  {message}  ")

  @pytest.mark.asyncio
  async def test_cache_disabled_runs_research_each_time(self, ponytail_cache_mode):
    config.PONYTAIL_CACHE_BRIEF.__value__ = False
    question = "How do I migrate from Stripe API 2023-10-16 to 2024-06-20?"
    brief = ResearchBrief(query="stripe api migration")
    brief.facts = ["Checkout session fields changed in 2024-06-20"]

    with request_context():
      chat = ch.Chat.from_conversation([{"role": "user", "content": question}])
      llm = MagicMock(module=ponytail.ID_PREFIX)
      llm.emit_status = AsyncMock()
      llm.stream_final_completion = AsyncMock()

      with (
        patch.object(ponytail, "plan_search_queries", new=AsyncMock(return_value=["stripe api migration"])) as plan,
        patch.object(ponytail, "run_research_loop", new=AsyncMock(return_value=(brief, 0))) as run_loop,
      ):
        await ponytail.apply(chat, llm)
        await ponytail.apply(chat, llm)

    assert plan.await_count == 2
    assert run_loop.await_count == 2

  @pytest.mark.asyncio
  async def test_cache_enabled_reuses_brief_for_same_question(self, ponytail_cache_mode):
    config.PONYTAIL_CACHE_BRIEF.__value__ = True
    question = "How do I migrate from Stripe API 2023-10-16 to 2024-06-20?"
    brief = ResearchBrief(query="stripe api migration")
    brief.facts = ["Checkout session fields changed in 2024-06-20"]

    with request_context():
      chat = ch.Chat.from_conversation([{"role": "user", "content": question}])
      llm = MagicMock(module=ponytail.ID_PREFIX)
      llm.emit_status = AsyncMock()
      llm.stream_final_completion = AsyncMock()

      with (
        patch.object(ponytail, "plan_search_queries", new=AsyncMock(return_value=["stripe api migration"])) as plan,
        patch.object(ponytail, "run_research_loop", new=AsyncMock(return_value=(brief, 0))) as run_loop,
      ):
        await ponytail.apply(chat, llm)
        await ponytail.apply(chat, llm)

    plan.assert_awaited_once()
    run_loop.assert_awaited_once()
    statuses = [call.args[0] for call in llm.emit_status.await_args_list]
    assert any("using cached brief" in status for status in statuses)

  @pytest.mark.asyncio
  async def test_cache_enabled_runs_research_for_different_question(self, ponytail_cache_mode):
    config.PONYTAIL_CACHE_BRIEF.__value__ = True
    first_question = "How do I migrate from Stripe API 2023-10-16 to 2024-06-20?"
    second_question = "Compare Kubernetes 1.29 vs 1.30 API deprecations"
    first_brief = ResearchBrief(query="stripe api migration")
    first_brief.facts = ["Checkout session fields changed in 2024-06-20"]
    second_brief = ResearchBrief(query="k8s deprecations")
    second_brief.facts = ["Batch v1beta1 removed in 1.30"]

    with request_context():
      first_chat = ch.Chat.from_conversation([{"role": "user", "content": first_question}])
      second_chat = ch.Chat.from_conversation([{"role": "user", "content": second_question}])
      llm = MagicMock(module=ponytail.ID_PREFIX)
      llm.emit_status = AsyncMock()
      llm.stream_final_completion = AsyncMock()

      with (
        patch.object(
          ponytail,
          "plan_search_queries",
          new=AsyncMock(side_effect=[["stripe api migration"], ["k8s 1.30 deprecations"]]),
        ) as plan,
        patch.object(
          ponytail,
          "run_research_loop",
          new=AsyncMock(side_effect=[(first_brief, 0), (second_brief, 0)]),
        ) as run_loop,
      ):
        await ponytail.apply(first_chat, llm)
        await ponytail.apply(second_chat, llm)

    assert plan.await_count == 2
    assert run_loop.await_count == 2
    assert render_to_system(second_brief) in second_chat.history()[0]["content"]


class TestPonytailStatusFormatting:
  def test_format_skipped_status_includes_gate_reason(self):
    assert ponytail.format_skipped_status("acknowledgment") == (
      "Ponytail research: skipped (acknowledgment)"
    )
    assert ponytail.format_skipped_status("not_research_heavy") == (
      "Ponytail research: skipped (not_research_heavy)"
    )

  def test_format_hop_query_status_matches_caveman_style(self):
    assert ponytail.format_hop_query_status(1, 1) == (
      "Ponytail research: hop 1 (1 query)..."
    )
    assert ponytail.format_hop_query_status(2, 3) == (
      "Ponytail research: hop 2 (3 queries)..."
    )

  def test_format_hop_gathered_status_includes_hop_query_and_url_counts(self):
    assert ponytail.format_hop_gathered_status(hop=1, query_count=2, pages_read=1) == (
      "Ponytail research: hop 1, 2 queries, read 1 URL..."
    )
    assert ponytail.format_hop_gathered_status(hop=2, query_count=1, pages_read=0) == (
      "Ponytail research: hop 2, 1 query, read 0 URLs..."
    )

  def test_format_early_exit_status_includes_gathered_chars_and_threshold(self):
    assert ponytail.format_early_exit_status(
      gathered_chars=15000,
      threshold=15000,
    ) == (
      "Ponytail research: early exit (hop 1 gathered 15000 chars, "
      "threshold 15000), skipping hop 2..."
    )


class TestPonytailApply:
  @pytest.mark.asyncio
  async def test_apply_passes_through_on_skip(self):
    chat = ch.Chat.from_conversation([{"role": "user", "content": "thanks"}])
    llm = MagicMock(module=ponytail.ID_PREFIX)
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    with patch.object(ponytail, "plan_search_queries", new=AsyncMock()) as plan:
      await ponytail.apply(chat, llm)

    plan.assert_not_called()
    llm.emit_status.assert_awaited_once_with(
      "Ponytail research: skipped (acknowledgment)"
    )
    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_apply_passes_through_when_no_queries_planned(self):
    chat = ch.Chat.from_conversation([
      {
        "role": "user",
        "content": "What are the breaking changes when migrating from FastAPI 0.100 to 0.115?",
      },
    ])
    llm = MagicMock(module=ponytail.ID_PREFIX)
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    with (
      patch.object(ponytail, "plan_search_queries", new=AsyncMock(return_value=[])),
      patch.object(ponytail, "run_research_loop", new=AsyncMock()) as run_loop,
    ):
      await ponytail.apply(chat, llm)

    run_loop.assert_not_called()
    statuses = [call.args[0] for call in llm.emit_status.await_args_list]
    assert statuses == [
      "Ponytail research: planning queries...",
      "Ponytail research: skipped (no_queries_planned)",
    ]
    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_apply_injects_structured_brief_and_completes(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "How do I migrate from Stripe API 2023-10-16 to 2024-06-20?"},
    ])
    llm = MagicMock(module=ponytail.ID_PREFIX)
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    brief = ResearchBrief(query="stripe api migration")
    brief.facts = ["Checkout session fields changed in 2024-06-20"]
    brief.uncertainties = ["Webhook retry semantics unclear"]
    brief.recommendation = "Run Stripe's upgrade helper before changing endpoints."
    brief.do_not_assume = ["That legacy prices auto-migrate"]

    with (
      patch.object(ponytail, "plan_search_queries", new=AsyncMock(return_value=["stripe api migration"])),
      patch.object(ponytail, "run_research_loop", new=AsyncMock(return_value=(brief, 0))),
    ):
      await ponytail.apply(chat, llm)

    rendered = render_to_system(brief)
    assert rendered in chat.history()[0]["content"]
    assert "<facts>" in rendered
    assert "<recommendation>" in rendered
    assert "<do_not_assume>" in rendered
    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_apply_emits_phase_statuses(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Compare Kubernetes 1.29 vs 1.30 API deprecations"},
    ])
    llm = MagicMock(module=ponytail.ID_PREFIX)
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    with (
      patch("research.fetch.web_search", new=AsyncMock(return_value="1. [Docs](https://k8s.example) (Date: N/A)\nSnippet")),
      patch("research.fetch.read_url", new=AsyncMock(return_value="deprecation notes")),
      patch.object(ponytail, "plan_search_queries", new=AsyncMock(return_value=["k8s 1.30 deprecations"])),
      patch.object(ponytail, "detect_gaps", new=AsyncMock(return_value=ponytail.GapAnalysis())),
      patch.object(
        ponytail,
        "synthesize_brief",
        new=AsyncMock(side_effect=lambda _c, _l, _m, brief: brief),
      ),
    ):
      await ponytail.apply(chat, llm)

    statuses = [call.args[0] for call in llm.emit_status.await_args_list]
    assert statuses[0] == "Ponytail research: planning queries..."
    assert any("hop 1 (1 query)" in status for status in statuses)
    assert any("hop 1, 1 query, read" in status for status in statuses)
    assert any("synthesizing brief" in status for status in statuses)

  @pytest.mark.asyncio
  async def test_apply_injects_research_unavailable_note_on_total_failure(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "How do I migrate from Stripe API 2023-10-16 to 2024-06-20?"},
    ])
    llm = MagicMock(module=ponytail.ID_PREFIX)
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    brief = ResearchBrief(query="stripe api migration")
    brief.add_note(RESEARCH_UNAVAILABLE_NOTE)

    with (
      patch.object(ponytail, "plan_search_queries", new=AsyncMock(return_value=["stripe api migration"])),
      patch.object(ponytail, "run_research_loop", new=AsyncMock(return_value=(brief, 0))),
      patch.object(ponytail.brief_mod, "has_usable_research", return_value=False),
    ):
      await ponytail.apply(chat, llm)

    rendered = render_to_system(brief)
    assert RESEARCH_UNAVAILABLE_NOTE in rendered
    statuses = [call.args[0] for call in llm.emit_status.await_args_list]
    assert any("research unavailable" in status for status in statuses)
    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_apply_uses_config_budget(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "What is the breaking change between OpenAPI 3.0 and 3.1?"},
    ])
    llm = MagicMock(module=ponytail.ID_PREFIX)
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    original = (
      config.PONYTAIL_MAX_SEARCHES.__value__,
      config.PONYTAIL_MAX_URL_READS.__value__,
      config.PONYTAIL_MAX_CHARS.__value__,
    )
    try:
      config.PONYTAIL_MAX_SEARCHES.__value__ = 5
      config.PONYTAIL_MAX_URL_READS.__value__ = 4
      config.PONYTAIL_MAX_CHARS.__value__ = 15000

      with (
        patch.object(ponytail, "plan_search_queries", new=AsyncMock(return_value=["openapi 3.1 changes"])),
        patch.object(ponytail, "run_research_loop", new=AsyncMock(return_value=(ResearchBrief(), 0))) as run_loop,
      ):
        await ponytail.apply(chat, llm)

      budget = run_loop.await_args.args[4]
      assert budget.max_searches == 5
      assert budget.max_url_reads == 4
      assert budget.max_chars == 15000
    finally:
      (
        config.PONYTAIL_MAX_SEARCHES.__value__,
        config.PONYTAIL_MAX_URL_READS.__value__,
        config.PONYTAIL_MAX_CHARS.__value__,
      ) = original