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
import workflows
from middleware.request_id import request_id_var
from modules import autocheck, caveman, keel, ponytail
from modules import workflows as workflow_presets
from state import request as request_state


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
      AsyncMock(
        return_value={
          "objective": "Migrate Stripe checkout auth",
          "constraints": ["Use latest Stripe API docs"],
          "acceptance_criteria": ["Auth uses checkout sessions", "Tests pass"],
          "in_scope_paths": ["services/boost/src/auth.py"],
        }
      )
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
    autocheck_cheap = _cheap_llm_mock(
      AsyncMock(
        return_value={
          "verdict": "pass",
          "summary": "Migration plan looks sound.",
          "findings": [],
        }
      )
    )

    with (
      request_context(),
      patch.object(keel, "_cheap_llm", return_value=keel_cheap),
      patch(
        "research.orchestrate.cheap_llm",
        side_effect=[caveman_cheap, ponytail_cheap, ponytail_cheap, ponytail_cheap],
      ),
      patch.object(autocheck, "_cheap_llm", return_value=autocheck_cheap),
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
    llm.stream_chat_completion.assert_awaited_once()
    keel_cheap.chat_completion.assert_awaited_once()
    caveman_cheap.chat_completion.assert_awaited_once()
    assert ponytail_cheap.chat_completion.await_count == 3
    autocheck_cheap.chat_completion.assert_awaited_once()
    llm.emit_message.assert_awaited_once_with("Draft implementation plan.")

    history = chat.history()
    contents = [msg.get("content") or "" for msg in history]
    assert any("provided tools" in content for content in contents)
    assert sum("<research_brief>" in content for content in contents) >= 2