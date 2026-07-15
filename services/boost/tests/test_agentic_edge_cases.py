"""Edge-case tests for agentic Boost modules and workflow presets."""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chat as ch
import config
import deliverable
import workflows
from modules import autocheck, caveman, deephop, diffscope, quickhop
from research.brief import RESEARCH_UNAVAILABLE_NOTE, ResearchBrief
from research.budget import ResearchBudget
import research.orchestrate as orchestrate


@pytest.fixture(autouse=True)
def reset_workflow_registry():
  workflows.invalidate_registry()
  yield
  workflows.invalidate_registry()


class TestQuickhopEdgeCases:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  @pytest.mark.asyncio
  async def test_continue_skips_research_without_module_prefix(self):
    chat = self._chat("continue")
    llm = MagicMock(module=None)
    assert quickhop.research_skip_reason(chat) is not None
    gate_reason, _ = await quickhop.research_gate_reason(chat, llm)
    assert gate_reason != "triggered"

  @pytest.mark.asyncio
  async def test_thanks_for_help_skips_research(self):
    chat = self._chat("thanks for the help!")
    llm = MagicMock(module=None)
    assert quickhop.research_skip_reason(chat) is not None
    gate_reason, _ = await quickhop.research_gate_reason(chat, llm)
    assert gate_reason != "triggered"

  @pytest.mark.asyncio
  async def test_version_question_triggers_research_without_module_prefix(self):
    chat = self._chat("What changed in Python 3.13 asyncio semantics?")
    llm = MagicMock(module=None)
    assert quickhop.research_skip_reason(chat) is None
    gate_reason, _ = await quickhop.research_gate_reason(chat, llm)
    assert gate_reason == "triggered"

  @pytest.mark.asyncio
  async def test_api_endpoint_question_triggers_research(self):
    chat = self._chat(
      "What is the Stripe checkout session API endpoint response format?"
    )
    llm = MagicMock(module=quickhop.ID_PREFIX)
    gate_reason, _ = await quickhop.research_gate_reason(chat, llm)
    assert gate_reason == "triggered"

  @pytest.mark.asyncio
  async def test_apply_passes_through_on_continue(self):
    chat = self._chat("carry on as planned")
    llm = MagicMock(module=quickhop.ID_PREFIX)
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    with patch.object(quickhop, "extract_search_queries", new=AsyncMock()) as extract:
      await quickhop.apply(chat, llm)

    extract.assert_not_called()
    llm.emit_status.assert_awaited_once_with(
      "Quickhop research: skipped (continuation)"
    )
    llm.stream_final_completion.assert_awaited_once()


class TestCavemanStyleEdgeCases:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  @pytest.mark.asyncio
  async def test_apply_passes_through_when_user_stops_style(self):
    chat = self._chat("stop caveman and answer normally.")
    llm = MagicMock()

    with patch(
      "modules.style.workflow_mod.complete_or_defer",
      new=AsyncMock(return_value="ok"),
    ) as complete_or_defer:
      await caveman.apply(chat, llm)

    assert not any("<caveman_style" in (msg.get("content") or "") for msg in chat.history())
    complete_or_defer.assert_awaited_once_with(llm, None)


class TestDeephopEdgeCases:
  @pytest.mark.asyncio
  async def test_mid_hop_budget_exhaustion_stops_remaining_first_hop_queries(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Compare API v1 vs v2 migration paths"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    budget = ResearchBudget(
      max_searches=1,
      max_url_reads=0,
      max_chars=5000,
    )

    with patch(
      "research.fetch.web_search",
      new=AsyncMock(return_value="1. [Docs](https://a.example) (Date: N/A)\nSnippet"),
    ) as web_search:
      brief = ResearchBrief(query="api migration")
      await orchestrate.run_searches(
        ["api v1 docs", "api v2 docs", "api migration guide"],
        budget,
        brief,
        module_id=deephop.ID_PREFIX,
        status_prefix="Deephop research",
        phase="Deephop hop 1",
      )

    assert web_search.await_count == 1
    assert budget.searches_used == 1
    assert any(
      "hop 1: search budget exhausted" in note.lower()
      for note in brief.notes
    )

  @pytest.mark.asyncio
  async def test_search_failure_degrades_gracefully_in_research_loop(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Migrate from FastAPI 0.100 to 0.115"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    budget = ResearchBudget(
      max_searches=2,
      max_url_reads=0,
      max_chars=5000,
    )

    with (
      patch(
        "research.fetch.web_search",
        new=AsyncMock(side_effect=RuntimeError("search provider down")),
      ),
      patch.object(deephop, "detect_gaps", new=AsyncMock(return_value=deephop.GapAnalysis())),
      patch.object(
        deephop,
        "synthesize_brief",
        new=AsyncMock(side_effect=lambda _c, _l, _m, brief: brief),
      ),
    ):
      brief, _ = await deephop.run_research_loop(
        chat,
        llm,
        "Migrate from FastAPI 0.100 to 0.115",
        ["fastapi migration"],
        budget,
      )

    assert any("search failed" in note.lower() for note in brief.notes)
    assert RESEARCH_UNAVAILABLE_NOTE in brief.notes
    assert brief.query == "Migrate from FastAPI 0.100 to 0.115"
    statuses = [call.args[0] for call in llm.emit_status.await_args_list]
    assert any("search failed" in status for status in statuses)

  @pytest.mark.asyncio
  async def test_read_failure_degrades_gracefully_in_research_loop(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Compare Kubernetes 1.29 vs 1.30 API deprecations"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    budget = ResearchBudget(
      max_searches=1,
      max_url_reads=1,
      max_chars=5000,
    )
    search_text = "1. [Docs](https://docs.example.com) (Date: N/A)\nSnippet"

    with (
      patch("research.fetch.web_search", new=AsyncMock(return_value=search_text)),
      patch(
        "research.fetch.read_url",
        new=AsyncMock(side_effect=ValueError("blocked by robots.txt")),
      ),
      patch.object(deephop, "detect_gaps", new=AsyncMock(return_value=deephop.GapAnalysis())),
      patch.object(
        deephop,
        "synthesize_brief",
        new=AsyncMock(side_effect=lambda _c, _l, _m, brief: brief),
      ),
    ):
      brief, _ = await deephop.run_research_loop(
        chat,
        llm,
        "Compare Kubernetes 1.29 vs 1.30 API deprecations",
        ["k8s 1.30 deprecations"],
        budget,
      )

    assert brief.pages == []
    assert any("could not read" in note.lower() for note in brief.notes)
    statuses = [call.args[0] for call in llm.emit_status.await_args_list]
    assert any("could not read" in status for status in statuses)


class TestAutocheckEdgeCases:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  def test_thanks_does_not_trigger_autocheck(self):
    chat = self._chat("thanks")
    assert not autocheck.needs_autocheck(chat)
    assert autocheck.autocheck_gate_reason(chat) == "acknowledgment"

  def test_thanks_for_help_does_not_trigger_autocheck(self):
    chat = self._chat("thanks for the help!")
    assert not autocheck.needs_autocheck(chat)
    assert autocheck.autocheck_gate_reason(chat) == "acknowledgment"

  def test_explain_code_does_not_trigger_autocheck_or_diffscope(self):
    chat = self._chat("Explain this function in services/boost/src/utils.py")
    assert not deliverable.is_coding_deliverable(chat)
    assert not autocheck.needs_autocheck(chat)
    assert not diffscope.needs_diffscope(chat)

  def test_two_signal_code_deliverable_triggers_autocheck(self):
    chat = self._chat("Implement retry helper in services/boost/src/utils.py")
    assert deliverable.count_deliverable_signals(chat) >= 2
    assert autocheck.needs_autocheck(chat)
    assert autocheck.autocheck_gate_reason(chat) == "triggered"

  @pytest.mark.asyncio
  async def test_apply_passes_through_on_thanks(self):
    chat = self._chat("thanks")
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    with patch.object(autocheck, "generate_draft", new=AsyncMock()) as draft:
      await autocheck.apply(chat, llm)

    draft.assert_not_called()
    llm.emit_status.assert_awaited_once_with("Autocheck: skipped (acknowledgment)")
    llm.stream_final_completion.assert_awaited_once()


class TestDiffscopeEdgeCases:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  def test_only_edit_foo_py_extracts_allowed_scope(self):
    message = "Implement the retry helper but only edit foo.py"
    scope = diffscope.extract_user_scope(self._chat(message))
    assert scope.allowed == ["foo.py"]
    assert scope.has_constraints
    assert diffscope.needs_diffscope(self._chat(message))

  def test_only_edit_foo_py_flags_bar_py_as_out_of_scope(self):
    scope = diffscope.UserScope(allowed=["foo.py"])
    violations = diffscope.find_violations(["src/foo.py", "src/bar.py"], scope)
    assert len(violations) == 1
    assert violations[0].path == "src/bar.py"
    assert violations[0].reason == "out_of_scope"

  @pytest.mark.asyncio
  async def test_apply_enforces_only_edit_foo_py(self):
    chat = self._chat("Implement the retry helper but only edit foo.py")
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()
    llm.stream_chat_completion = AsyncMock(
      return_value="Updated `src/foo.py` and `src/bar.py` for consistency.",
    )

    with (
      patch.object(diffscope, "verify_workspace_paths", new=AsyncMock(return_value=[])),
      patch.object(
        diffscope,
        "revise_with_correction",
        new=AsyncMock(return_value="Only updated `src/foo.py`."),
      ) as revise,
    ):
      await diffscope.apply(chat, llm)

    revise.assert_awaited_once()
    llm.emit_message.assert_awaited_once_with("Only updated `src/foo.py`.")
