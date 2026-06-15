"""End-to-end tests for the shipyard agentic coding workflow."""

import os
import sys
import uuid
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chat as ch
import deliverable
import workflows
from middleware.request_id import request_id_var
from modules import autocheck, caveman, keel, ponytail
from modules import workflows as workflow_presets
from modules.keel import TaskBrief, inject_brief_marker, store_brief
from state import request as request_state
from helpers import mock_cheap_llm


SHIPYARD_MODULE_ORDER = [
  "keel",
  "caveman",
  "tools",
  "ponytail",
  "autocheck",
  "final",
]

SHIPYARD_USER_MESSAGE = (
  "Implement Stripe checkout session auth migration in services/boost/src/auth.py "
  "using the latest API documentation."
)

RESEARCH_ONLY_MESSAGE = (
  "What is the Stripe checkout session API endpoint response format in 2024?"
)

MOCK_SEARCH_RESULT = (
  "1. [Stripe Checkout API](https://docs.stripe.com/checkout) (Date: N/A)\n"
  "Checkout session fields and migration notes."
)
MOCK_PAGE_CONTENT = "Stripe checkout session API reference for 2024-06-20."


@pytest.fixture(autouse=True)
def reset_workflow_registry():
  workflows.invalidate_registry()
  yield
  workflows.invalidate_registry()


@contextmanager
def request_context(request_id: str | None = None):
  request_id = request_id or f"shipyard-{uuid.uuid4().hex[:8]}"
  req = MagicMock()
  req.state = type("State", (), {})()
  token_req = request_state.set(req)
  token_id = request_id_var.set(request_id)
  try:
    yield req
  finally:
    request_state.reset(token_req)
    request_id_var.reset(token_id)
    for attr in ("local_tools", "keel_task_brief", "keel_met_criteria"):
      if hasattr(req.state, attr):
        delattr(req.state, attr)


def _make_llm() -> MagicMock:
  llm = MagicMock()
  llm.url = "http://example.com"
  llm.headers = {}
  llm.query_params = {}
  llm.model = "test-model"
  llm.module = None
  llm.is_final_stream = False
  llm.emit_status = AsyncMock()
  llm.emit_message = AsyncMock()
  llm.stream_chat_completion = AsyncMock(return_value="Draft implementation plan.")
  return llm


def _cheap_llm_mock(chat_completion: AsyncMock) -> MagicMock:
  cheap = MagicMock()
  cheap.chat_completion = chat_completion
  return cheap


def _implementation_brief() -> TaskBrief:
  return TaskBrief(
    objective="Migrate Stripe checkout auth",
    constraints=["Use latest Stripe API docs"],
    acceptance_criteria=["Auth uses checkout sessions", "Tests pass"],
    in_scope_paths=["services/boost/src/auth.py"],
  )


IMPLEMENTATION_TURN_MESSAGE = (
  "Fix the retry helper in services/boost/src/utils.py"
)

IMPLEMENTATION_WITH_RESEARCH_MESSAGE = (
  "Implement OAuth against the latest Stripe API documentation for checkout sessions."
)


class TestShipyardTurnTypes:
  def test_is_implementation_turn_detects_action_and_path_without_research(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": IMPLEMENTATION_TURN_MESSAGE},
    ])
    assert deliverable.is_implementation_turn(chat)
    assert deliverable.has_file_path_mention(IMPLEMENTATION_TURN_MESSAGE)
    assert not deliverable.has_research_signals(IMPLEMENTATION_TURN_MESSAGE)

  def test_is_implementation_turn_detects_bare_filename_without_research(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement the helper in utils.py"},
    ])
    assert deliverable.is_implementation_turn(chat)

  def test_is_implementation_turn_false_when_research_signals_present(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": IMPLEMENTATION_WITH_RESEARCH_MESSAGE},
    ])
    assert deliverable.has_research_signals(IMPLEMENTATION_WITH_RESEARCH_MESSAGE)
    assert not deliverable.is_implementation_turn(chat)

  def test_is_implementation_turn_false_for_shipyard_migration_with_docs(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": SHIPYARD_USER_MESSAGE},
    ])
    assert not deliverable.is_implementation_turn(chat)

  def test_is_implementation_turn_false_for_research_only_question(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": RESEARCH_ONLY_MESSAGE},
    ])
    assert not deliverable.is_implementation_turn(chat)

  @pytest.mark.asyncio
  async def test_caveman_skips_implementation_turn_without_keel_brief(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": IMPLEMENTATION_TURN_MESSAGE},
    ])
    assert caveman.research_skip_reason(chat) == "implementation_turn"
    assert caveman.should_skip_research(chat)
    assert not await caveman.needs_research(chat, MagicMock(module=caveman.ID_PREFIX))

  @pytest.mark.asyncio
  async def test_ponytail_skips_implementation_turn(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": IMPLEMENTATION_TURN_MESSAGE},
    ])
    assert ponytail.research_skip_reason(chat) == "implementation_turn"
    assert ponytail.should_skip_research(chat)
    llm = MagicMock(module=ponytail.ID_PREFIX)
    assert not await ponytail.needs_research(chat, llm)

  @pytest.mark.asyncio
  async def test_caveman_skips_when_keel_brief_is_implementation(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": SHIPYARD_USER_MESSAGE},
    ])
    brief = _implementation_brief()
    with request_context():
      inject_brief_marker(chat, brief)
      store_brief(brief)

      assert keel.is_implementation_brief(brief)
      assert caveman.should_skip_research(chat)
      assert not await caveman.needs_research(chat, MagicMock(module=caveman.ID_PREFIX))

  @pytest.mark.asyncio
  async def test_caveman_runs_for_research_only_turn_without_implementation_brief(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": RESEARCH_ONLY_MESSAGE},
    ])
    assert deliverable.is_research_only_turn(chat)
    assert not caveman.should_skip_research(chat)
    llm = MagicMock(module=caveman.ID_PREFIX)
    assert await caveman.needs_research(chat, llm)

  def test_autocheck_skips_research_only_turn(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": RESEARCH_ONLY_MESSAGE},
    ])
    assert not autocheck.needs_autocheck(chat)
    assert autocheck.autocheck_gate_reason(chat) == "research_only"

  def test_autocheck_triggers_on_implementation_deliverable(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": SHIPYARD_USER_MESSAGE},
    ])
    assert autocheck.needs_autocheck(chat)


class TestShipyardDeferFinal:
  @pytest.mark.asyncio
  async def test_prep_modules_defer_final_until_explicit_final_step(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": RESEARCH_ONLY_MESSAGE},
    ])
    llm = _make_llm()
    stream_calls: list[str] = []

    async def tracked_final(**_kwargs):
      stream_calls.append("final")
      llm.is_final_stream = True
      return "Final streamed answer."

    llm.stream_final_completion = AsyncMock(side_effect=tracked_final)

    ponytail_cheap = _cheap_llm_mock(
      AsyncMock(
        side_effect=[
          {"queries": ["Stripe checkout session API response format 2024"]},
          {"gaps": [], "follow_up_queries": []},
          {
            "facts": ["Response includes id, url, and status fields"],
            "uncertainties": [],
            "recommendation": "Use official Stripe docs.",
            "do_not_assume": [],
          },
        ]
      )
    )

    with (
      request_context(),
      patch(
        "research.orchestrate.cheap_llm",
        return_value=ponytail_cheap,
      ),
      patch("research.fetch.web_search", new=AsyncMock(return_value=MOCK_SEARCH_RESULT)),
      patch("research.fetch.read_url", new=AsyncMock(return_value=MOCK_PAGE_CONTENT)),
    ):
      await workflows.apply_workflow(
        deepcopy(workflow_presets.PRESETS["shipyard"]),
        chat,
        llm,
      )

    assert stream_calls == ["final"]
    assert llm.stream_final_completion.await_count == 1

  @pytest.mark.asyncio
  async def test_autocheck_pass_through_defers_on_research_only_shipyard_turn(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": RESEARCH_ONLY_MESSAGE},
    ])
    llm = _make_llm()
    llm.stream_final_completion = AsyncMock()

    with patch.object(autocheck, "generate_draft", new=AsyncMock()) as draft:
      await autocheck.apply(chat, llm, config={"defer_final": True})

    draft.assert_not_called()
    llm.stream_final_completion.assert_not_called()


class TestShipyardWorkflowE2E:
  @pytest.mark.asyncio
  async def test_shipyard_executes_module_chain_in_order_with_mocked_llm(self):
    """Run shipyard end-to-end with mocked LLM/fetch; verify module order."""
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": SHIPYARD_USER_MESSAGE},
    ])
    llm = _make_llm()
    execution_order: list[str] = []
    real_apply_module = workflows._apply_module

    async def tracking_apply_module(module_name, module_cfg, chat_obj, llm_obj):
      execution_order.append(module_name)
      return await real_apply_module(module_name, module_cfg, chat_obj, llm_obj)

    async def tracked_final(**_kwargs):
      execution_order.append("final")
      llm.is_final_stream = True
      return "Final streamed answer."

    llm.stream_final_completion = AsyncMock(side_effect=tracked_final)

    keel_cheap = _cheap_llm_mock(
      AsyncMock(return_value=_implementation_brief().model_dump())
    )
    caveman_cheap = _cheap_llm_mock(
      AsyncMock(return_value={"queries": ["Stripe checkout session API migration"]})
    )
    ponytail_cheap = _cheap_llm_mock(
      AsyncMock(
        side_effect=[
          {"queries": ["Stripe checkout session migration guide"]},
          {"gaps": [], "follow_up_queries": []},
          {
            "facts": ["Use `Stripe 2024-06-20` checkout session API"],
            "uncertainties": ["Verify webhook fields in official docs"],
            "recommendation": "Read Stripe checkout docs before editing auth.py.",
            "do_not_assume": ["Do not assume legacy endpoints still work"],
          },
        ]
      )
    )
    autocheck_cheap = mock_cheap_llm(
      stream_chat_completion=AsyncMock(return_value="Draft implementation plan."),
      chat_completion=AsyncMock(
        return_value={
          "verdict": "pass",
          "summary": "Migration plan looks sound.",
          "findings": [],
        },
      ),
    )

    with (
      request_context(),
      patch(
        "research.orchestrate.cheap_llm",
        side_effect=[
          keel_cheap,
          ponytail_cheap,
          ponytail_cheap,
          ponytail_cheap,
          autocheck_cheap,
          autocheck_cheap,
        ],
      ),
      patch("research.fetch.web_search", new=AsyncMock(return_value=MOCK_SEARCH_RESULT)),
      patch("research.fetch.read_url", new=AsyncMock(return_value=MOCK_PAGE_CONTENT)),
      patch.object(workflows, "_apply_module", new=tracking_apply_module),
    ):
      await workflows.apply_workflow(
        deepcopy(workflow_presets.PRESETS["shipyard"]),
        chat,
        llm,
      )

    assert execution_order == SHIPYARD_MODULE_ORDER
    assert llm.stream_final_completion.await_count == 1
    autocheck_cheap.stream_chat_completion.assert_awaited_once()
    keel_cheap.chat_completion.assert_awaited_once()
    caveman_cheap.chat_completion.assert_not_called()
    assert ponytail_cheap.chat_completion.await_count == 3
    autocheck_cheap.chat_completion.assert_awaited_once()
    llm.emit_message.assert_awaited_once_with("Draft implementation plan.")

    history = chat.history()
    contents = [msg.get("content") or "" for msg in history]
    assert any("provided tools" in content for content in contents)
    assert sum("<research_brief>" in content for content in contents) == 1

  @pytest.mark.asyncio
  async def test_shipyard_research_only_turn_skips_autocheck_audit(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": RESEARCH_ONLY_MESSAGE},
    ])
    llm = _make_llm()

    async def tracked_final(**_kwargs):
      llm.is_final_stream = True
      return "Research answer."

    llm.stream_final_completion = AsyncMock(side_effect=tracked_final)

    ponytail_cheap = _cheap_llm_mock(
      AsyncMock(
        side_effect=[
          {"queries": ["Stripe checkout session API response format 2024"]},
          {"gaps": [], "follow_up_queries": []},
          {
            "facts": ["Response includes id, url, and status fields"],
            "uncertainties": [],
            "recommendation": "Use official Stripe docs.",
            "do_not_assume": [],
          },
        ]
      )
    )

    with (
      request_context(),
      patch(
        "research.orchestrate.cheap_llm",
        return_value=ponytail_cheap,
      ),
      patch("research.fetch.web_search", new=AsyncMock(return_value=MOCK_SEARCH_RESULT)),
      patch("research.fetch.read_url", new=AsyncMock(return_value=MOCK_PAGE_CONTENT)),
      patch.object(autocheck, "run_audit", new=AsyncMock()) as run_audit,
    ):
      await workflows.apply_workflow(
        deepcopy(workflow_presets.PRESETS["shipyard"]),
        chat,
        llm,
      )

    run_audit.assert_not_called()
    assert llm.stream_final_completion.await_count == 1