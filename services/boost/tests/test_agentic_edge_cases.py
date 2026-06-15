"""Edge-case tests for agentic Boost modules and workflow presets."""

import os
import sys
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chat as ch
import deliverable
import workflows
from modules import autocheck, caveman, diffscope, keel, ponytail
from modules import workflows as workflow_presets
from research.brief import RESEARCH_UNAVAILABLE_NOTE, ResearchBrief
from research.budget import ResearchBudget
import research.orchestrate as orchestrate


SHIPYARD_MODULE_ORDER = [
  "keel",
  "caveman",
  "tools",
  "ponytail",
  "autocheck",
  "final",
]


@pytest.fixture(autouse=True)
def reset_workflow_registry():
  workflows.invalidate_registry()
  yield
  workflows.invalidate_registry()


class TestCavemanEdgeCases:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  @pytest.mark.asyncio
  async def test_continue_skips_research_without_module_prefix(self):
    chat = self._chat("continue")
    llm = MagicMock(module=None)
    assert caveman.should_skip_research(chat)
    assert not await caveman.needs_research(chat, llm)

  @pytest.mark.asyncio
  async def test_thanks_for_help_skips_research(self):
    chat = self._chat("thanks for the help!")
    llm = MagicMock(module=None)
    assert caveman.should_skip_research(chat)
    assert not await caveman.needs_research(chat, llm)

  @pytest.mark.asyncio
  async def test_version_question_triggers_research_without_module_prefix(self):
    chat = self._chat("What changed in Python 3.13 asyncio semantics?")
    llm = MagicMock(module=None)
    assert not caveman.should_skip_research(chat)
    assert await caveman.needs_research(chat, llm)

  @pytest.mark.asyncio
  async def test_api_endpoint_question_triggers_research(self):
    chat = self._chat(
      "What is the Stripe checkout session API endpoint response format?"
    )
    llm = MagicMock(module=caveman.ID_PREFIX)
    assert await caveman.needs_research(chat, llm)

  @pytest.mark.asyncio
  async def test_apply_passes_through_on_continue(self):
    chat = self._chat("continue")
    llm = MagicMock(module=caveman.ID_PREFIX)
    llm.stream_final_completion = AsyncMock()

    with patch.object(caveman, "extract_search_queries", new=AsyncMock()) as extract:
      await caveman.apply(chat, llm)

    extract.assert_not_called()
    llm.stream_final_completion.assert_awaited_once()


class TestPonytailEdgeCases:
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
      patch.object(ponytail, "detect_gaps", new=AsyncMock(return_value=ponytail.GapAnalysis())),
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
      patch.object(ponytail, "detect_gaps", new=AsyncMock(return_value=ponytail.GapAnalysis())),
      patch.object(
        ponytail,
        "synthesize_brief",
        new=AsyncMock(side_effect=lambda _c, _l, _m, brief: brief),
      ),
    ):
      brief, _ = await ponytail.run_research_loop(
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


class TestKeelEdgeCases:
  def _chat(self, *messages: str) -> ch.Chat:
    conversation = [{"role": "user", "content": msg} for msg in messages]
    return ch.Chat.from_conversation(conversation)

  def test_drift_detected_on_also_refactor_phrase(self):
    assert keel.detect_drift("Can you also refactor the auth module while you're here?")

  def test_anchor_not_injected_on_first_turn(self):
    chat = self._chat("Implement retry helper in services/boost/src/utils.py")
    assert keel.count_user_turns(chat) == 1

  @pytest.mark.asyncio
  async def test_apply_skips_anchor_on_third_user_turn_with_default_throttle(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
      {"role": "assistant", "content": "Added retry helper with three attempts."},
      {"role": "user", "content": "Add logging around retries."},
      {"role": "assistant", "content": "Added structured logging."},
      {"role": "user", "content": "Tighten the timeout handling."},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    brief = keel.TaskBrief(
      objective="Add retry helper",
      acceptance_criteria=["Helper retries 3 times", "Tests pass"],
      in_scope_paths=["services/boost/src/utils.py"],
    )

    with (
      patch.object(keel, "get_stored_brief", return_value=brief),
      patch.object(keel, "hydrate_brief_from_chat", return_value=None),
      patch.object(keel, "update_met_criteria_from_history", return_value=set()),
      patch.object(keel, "_register_finish_wrapper"),
    ):
      await keel.apply(chat, llm)

    assert keel.count_user_turns(chat) == 3
    history = chat.history()
    assert not any("<task_anchor>" in (msg.get("content") or "") for msg in history)
    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_apply_injects_drift_warning_on_also_refactor(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
      {"role": "assistant", "content": "Added retry helper."},
      {"role": "user", "content": "Can you also refactor the auth module?"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    brief = keel.TaskBrief(
      objective="Add retry helper",
      acceptance_criteria=["Helper retries 3 times"],
      in_scope_paths=["services/boost/src/utils.py"],
    )

    with (
      patch.object(keel, "get_stored_brief", return_value=brief),
      patch.object(keel, "update_met_criteria_from_history", return_value=set()),
      patch.object(keel, "_register_finish_wrapper"),
    ):
      await keel.apply(chat, llm)

    history = chat.history()
    assert any(keel.DRIFT_WARNING in (msg.get("content") or "") for msg in history)
    llm.emit_status.assert_awaited_with(keel.DRIFT_STATUS)


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


class TestWorkflowEdgeCases:
  def test_shipyard_preset_module_order_exact(self):
    preset = workflow_presets.PRESETS["shipyard"]
    module_names = []
    for module_config in preset["modules"]:
      if isinstance(module_config, str):
        module_names.append(module_config)
      else:
        module_names.append(module_config["module"])
    assert module_names == SHIPYARD_MODULE_ORDER

  def test_shipyard_shorthand_matches_exact_module_order(self):
    assert workflow_presets.SHORTHAND["shipyard"] == ",".join(SHIPYARD_MODULE_ORDER)

  @pytest.mark.asyncio
  async def test_shipyard_apply_workflow_runs_modules_in_order(self):
    chat = MagicMock()
    llm = MagicMock()
    llm.is_final_stream = False
    llm.stream_final_completion = AsyncMock()

    with patch.object(workflows, "_apply_module", new_callable=AsyncMock) as mock_apply:
      await workflows.apply_workflow(
        deepcopy(workflow_presets.PRESETS["shipyard"]),
        chat,
        llm,
      )

    applied = [call.args[0] for call in mock_apply.await_args_list]
    assert applied == SHIPYARD_MODULE_ORDER[:-1]