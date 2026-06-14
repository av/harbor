"""Unit tests for the ponytail Boost module."""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chat as ch
import config
from modules import ponytail
from research.brief import RESEARCH_UNAVAILABLE_NOTE, ResearchBrief, render_to_system
from research.budget import ResearchBudget


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

  def test_needs_research_for_migration_with_module_prefix(self):
    chat = self._chat("Plan a migration from Django 4.2 to 5.0 for our auth layer.")
    llm = MagicMock(module=ponytail.ID_PREFIX)
    assert ponytail.needs_research(chat, llm)

  def test_skips_implementation_without_research_signals_even_with_prefix(self):
    chat = self._chat("Implement the helper in utils.py")
    llm = MagicMock(module=ponytail.ID_PREFIX)
    assert not ponytail.needs_research(chat, llm)

  def test_needs_research_without_prefix_only_for_research_heavy(self):
    chat = self._chat("Summarize how Harbor Boost modules are loaded.")
    llm = MagicMock(module=None)
    assert not ponytail.needs_research(chat, llm)

  def test_needs_research_without_prefix_for_version_compare(self):
    chat = self._chat("Compare React 18 vs 19 migration breaking changes")
    llm = MagicMock(module=None)
    assert ponytail.needs_research(chat, llm)


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
    ]


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
      brief = await ponytail.run_research_loop(
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
      brief = await ponytail.run_research_loop(
        chat,
        llm,
        "Compare API v1 vs v2 behavior",
        ["api v1 docs", "api v2 docs"],
        budget,
      )

    assert budget.searches_used == 1
    assert any("second research hop skipped" in note.lower() for note in brief.notes)


class TestPonytailApply:
  @pytest.mark.asyncio
  async def test_apply_passes_through_on_skip(self):
    chat = ch.Chat.from_conversation([{"role": "user", "content": "thanks"}])
    llm = MagicMock(module=ponytail.ID_PREFIX)
    llm.stream_final_completion = AsyncMock()

    with patch.object(ponytail, "plan_search_queries", new=AsyncMock()) as plan:
      await ponytail.apply(chat, llm)

    plan.assert_not_called()
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
      patch.object(ponytail, "run_research_loop", new=AsyncMock(return_value=brief)),
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
    assert any("hop 1" in status for status in statuses)
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
      patch.object(ponytail, "run_research_loop", new=AsyncMock(return_value=brief)),
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
        patch.object(ponytail, "run_research_loop", new=AsyncMock(return_value=ResearchBrief())) as run_loop,
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