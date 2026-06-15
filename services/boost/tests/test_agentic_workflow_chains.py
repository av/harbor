"""Integration tests for agentic workflow chains with mocked LLM."""

import ast
import os
import sys
import uuid
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chat as ch
import config
import tools.registry as tool_registry
import workflows
from middleware.request_id import request_id_var
from modules import autocheck, caveman, diffscope, ponytail, sightline
from modules import tools as tools_module
from modules import workflows as workflow_presets
from state import request as request_state
from helpers import mock_autocheck_cheap_llm


CODE_CHECK_MODULE_ORDER = ["tools", "autocheck", "final"]
SCOPE_GUARD_MODULE_ORDER = ["tools", "diffscope", "autocheck", "final"]
AGENT_CODE_MODULE_ORDER = ["tools", "sightline", "diffscope", "autocheck", "final"]
RESEARCH_QUICK_MODULE_ORDER = ["tools", "caveman", "final"]
RESEARCH_DEEP_MODULE_ORDER = ["tools", "ponytail", "final"]
AGENT_RESEARCH_MODULE_ORDER = ["tools", "caveman", "final"]

CODE_CHECK_USER_MESSAGE = (
  "Implement retry helper with exponential backoff in services/boost/src/utils.py"
)

SCOPE_GUARD_USER_MESSAGE = (
  "Fix the bug in services/boost/src/utils.py only — do not touch other files"
)

SCOPE_GUARD_VIOLATION_USER_MESSAGE = (
  "Fix the bug but only edit src/foo.py — do not touch other files"
)

AGENT_CODE_USER_MESSAGE = (
  "Implement retry helper with exponential backoff but only edit src/foo.py — "
  "do not touch other files"
)

RESEARCH_QUICK_USER_MESSAGE = (
  "What is the Stripe checkout session API endpoint response format in 2024?"
)

RESEARCH_DEEP_USER_MESSAGE = (
  "Migrate from Django 4.2 to 5.0 — what breaking changes affect django.utils.six?"
)

AGENT_RESEARCH_USER_MESSAGE = (
  "Before wiring the Stripe webhook handler in services/boost/src/payments.py, "
  "what's the checkout session API endpoint response format in 2024?"
)

AGENT_RESEARCH_IMPLEMENTATION_MESSAGE = (
  "Fix the retry helper in services/boost/src/utils.py"
)

MOCK_SEARCH_RESULT = (
  "1. [Stripe Checkout API](https://docs.stripe.com/checkout) (Date: N/A)\n"
  "Checkout session response includes id, url, and status fields."
)
MOCK_PAGE_CONTENT = "Stripe checkout session API reference for 2024-06-20."

MOCK_PONYTAIL_HOP1_SEARCH = (
  "1. [Django upgrade guide](https://docs.djangoproject.com) (Date: N/A)\n"
  "General upgrade tips without explicit 5.0 release notes."
)
MOCK_PONYTAIL_HOP2_SEARCH = (
  "1. [Django 5.0 release notes](https://docs.djangoproject.com/en/5.0/releases/5.0/) "
  "(Date: N/A)\nDjango 5.0 removes django.utils.six."
)
MOCK_PONYTAIL_PAGE_CONTENT = "Sparse Django upgrade page without full changelog."


@pytest.fixture(autouse=True)
def reset_workflow_registry():
  workflows.invalidate_registry()
  yield
  workflows.invalidate_registry()


@contextmanager
def request_context(request_id: str | None = None):
  request_id = request_id or f"agentic-chain-{uuid.uuid4().hex[:8]}"
  req = MagicMock()
  req.state = type("State", (), {})()
  token_req = request_state.set(req)
  token_id = request_id_var.set(request_id)
  try:
    yield req
  finally:
    request_state.reset(token_req)
    request_id_var.reset(token_id)
    for attr in (
      "local_tools",
      "sightline_path_state",
      "sightline_seq",
      "keel_task_brief",
      "keel_met_criteria",
    ):
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
  llm.boost_params = {}
  llm.emit_status = AsyncMock()
  llm.emit_message = AsyncMock()
  llm.stream_chat_completion = AsyncMock(return_value="Draft implementation plan.")
  return llm


def _cheap_llm_mock(chat_completion: AsyncMock) -> MagicMock:
  cheap = MagicMock()
  cheap.chat_completion = chat_completion
  return cheap


def _ponytail_cheap_llm_mock() -> MagicMock:
  async def chat_completion_side_effect(**kwargs):
    schema = kwargs.get("schema")
    fields = getattr(schema, "model_fields", {})
    if "queries" in fields:
      return {
        "queries": [
          "django 4.2 to 5.0 migration guide",
          "django 5.0 breaking changes django.utils.six",
        ],
      }
    if "follow_up_queries" in fields:
      return {
        "gaps": ["No explicit Django 5.0 release notes cited"],
        "follow_up_queries": [
          "Django 5.0 release notes breaking changes",
          "django.utils.six removal django 5",
        ],
      }
    if "facts" in fields:
      return {
        "facts": ["Django 5.0 removes `django.utils.six`"],
        "uncertainties": ["Verify third-party deps support Django 5.0"],
        "recommendation": "Read official Django 5.0 release notes before migrating.",
        "do_not_assume": ["Do not assume django.utils.six shims still exist"],
      }
    return {}

  return _cheap_llm_mock(AsyncMock(side_effect=chat_completion_side_effect))


class TestCodeCheckWorkflowChain:
  @pytest.mark.asyncio
  async def test_code_check_runs_tools_autocheck_final_on_deliverable(self):
    """code-check: tools → autocheck → final; deliverable triggers audit."""
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": CODE_CHECK_USER_MESSAGE},
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

    audit = autocheck.AuditResult(verdict="pass", summary="Migration plan looks sound.")
    debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="pass")

    with (
      request_context(),
      patch(
        "research.orchestrate.cheap_llm",
        return_value=mock_autocheck_cheap_llm(
          draft_response="Draft implementation plan.",
        ),
      ),
      patch.object(autocheck, "gather_workspace_context", new=AsyncMock(return_value="")),
      patch.object(
        autocheck,
        "run_mechanical_preaudit",
        new=AsyncMock(return_value=("", [])),
      ),
      patch.object(autocheck, "run_audit", new=AsyncMock(return_value=(audit, debug))) as run_audit,
      patch.object(workflows, "_apply_module", new=tracking_apply_module),
    ):
      await workflows.apply_workflow(
        deepcopy(workflow_presets.PRESETS["code-check"]),
        chat,
        llm,
      )

    assert execution_order == CODE_CHECK_MODULE_ORDER
    assert autocheck.needs_autocheck(chat)
    run_audit.assert_awaited_once()
    assert llm.stream_final_completion.await_count == 1

    history = chat.history()
    contents = [msg.get("content") or "" for msg in history]
    assert any("provided tools" in content for content in contents)
    llm.emit_message.assert_awaited_once_with("Draft implementation plan.")

  @pytest.mark.asyncio
  async def test_code_check_skips_autocheck_on_research_question(self):
    """code-check: tools → autocheck → final; research question skips audit."""
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": RESEARCH_QUICK_USER_MESSAGE},
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
      return "Final research answer."

    llm.stream_final_completion = AsyncMock(side_effect=tracked_final)

    with (
      request_context(),
      patch.object(autocheck, "generate_draft", new=AsyncMock()) as generate_draft,
      patch.object(autocheck, "run_audit", new=AsyncMock()) as run_audit,
      patch.object(workflows, "_apply_module", new=tracking_apply_module),
    ):
      await workflows.apply_workflow(
        deepcopy(workflow_presets.PRESETS["code-check"]),
        chat,
        llm,
      )

    assert execution_order == CODE_CHECK_MODULE_ORDER
    assert autocheck.autocheck_gate_reason(chat) == "research_only"
    assert not autocheck.needs_autocheck(chat)
    generate_draft.assert_not_called()
    run_audit.assert_not_called()
    assert llm.stream_final_completion.await_count == 1
    llm.emit_status.assert_any_await("Autocheck: skipped (research_only)")

    history = chat.history()
    contents = [msg.get("content") or "" for msg in history]
    assert any("provided tools" in content for content in contents)


class TestScopeGuardWorkflowChain:
  @pytest.mark.asyncio
  async def test_scope_guard_runs_diffscope_autocheck_on_scoped_deliverable(self):
    """scope-guard: tools → diffscope → autocheck → final on scoped deliverable."""
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": SCOPE_GUARD_USER_MESSAGE},
    ])
    llm = _make_llm()
    execution_order: list[str] = []
    real_apply_module = workflows._apply_module

    async def tracking_apply_module(module_name, module_cfg, chat_obj, llm_obj):
      execution_order.append(module_name)
      return await real_apply_module(module_name, module_cfg, chat_obj, llm_obj)

    draft_response = "Updated services/boost/src/utils.py with the null check."

    async def stream_final_side_effect(**_kwargs):
      execution_order.append("final")
      llm.is_final_stream = True
      return "Final scoped fix."

    llm.stream_chat_completion = AsyncMock(return_value=draft_response)
    llm.stream_final_completion = AsyncMock(side_effect=stream_final_side_effect)

    audit = autocheck.AuditResult(verdict="pass", summary="Scoped fix looks correct.")
    debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="pass")

    with (
      request_context(),
      patch(
        "research.orchestrate.cheap_llm",
        return_value=mock_autocheck_cheap_llm(draft_response=draft_response),
      ),
      patch.object(diffscope, "verify_workspace_paths", new=AsyncMock(return_value=[])),
      patch.object(autocheck, "gather_workspace_context", new=AsyncMock(return_value="")),
      patch.object(
        autocheck,
        "run_mechanical_preaudit",
        new=AsyncMock(return_value=("", [])),
      ),
      patch.object(autocheck, "run_audit", new=AsyncMock(return_value=(audit, debug))) as run_audit,
      patch.object(workflows, "_apply_module", new=tracking_apply_module),
    ):
      await workflows.apply_workflow(
        deepcopy(workflow_presets.PRESETS["scope-guard"]),
        chat,
        llm,
      )

    assert execution_order == SCOPE_GUARD_MODULE_ORDER
    assert diffscope.needs_diffscope(chat)
    assert autocheck.needs_autocheck(chat)
    run_audit.assert_awaited_once()
    # diffscope drafts via stream_chat_completion(emit=False); workflow final streams once.
    assert llm.stream_chat_completion.await_count >= 1
    assert llm.stream_final_completion.await_count == 1

    history = chat.history()
    contents = [msg.get("content") or "" for msg in history]
    assert any("provided tools" in content for content in contents)

  @pytest.mark.asyncio
  async def test_scope_guard_revises_out_of_scope_draft_then_autocheck_audits(self):
    """scope-guard: draft touches bar.py; diffscope revises; autocheck audits."""
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": SCOPE_GUARD_VIOLATION_USER_MESSAGE},
    ])
    llm = _make_llm()
    execution_order: list[str] = []
    real_apply_module = workflows._apply_module

    async def tracking_apply_module(module_name, module_cfg, chat_obj, llm_obj):
      execution_order.append(module_name)
      return await real_apply_module(module_name, module_cfg, chat_obj, llm_obj)

    draft_with_violation = (
      "Updated `src/foo.py` and `src/bar.py` for consistency."
    )
    revised_answer = "Only updated `src/foo.py`."
    autocheck_draft = "Scoped null-check fix in `src/foo.py`."

    async def stream_final_side_effect(**_kwargs):
      execution_order.append("final")
      llm.is_final_stream = True
      return "Final scoped fix after revision."

    llm.stream_chat_completion = AsyncMock(return_value=draft_with_violation)
    llm.stream_final_completion = AsyncMock(side_effect=stream_final_side_effect)

    audit = autocheck.AuditResult(verdict="pass", summary="Scoped fix looks correct.")
    debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="pass")

    with (
      request_context(),
      patch(
        "research.orchestrate.cheap_llm",
        return_value=mock_autocheck_cheap_llm(draft_response=autocheck_draft),
      ),
      patch.object(diffscope, "verify_workspace_paths", new=AsyncMock(return_value=[])),
      patch.object(
        diffscope,
        "revise_with_correction",
        new=AsyncMock(return_value=revised_answer),
      ) as revise,
      patch.object(autocheck, "gather_workspace_context", new=AsyncMock(return_value="")),
      patch.object(
        autocheck,
        "run_mechanical_preaudit",
        new=AsyncMock(return_value=("", [])),
      ),
      patch.object(autocheck, "run_audit", new=AsyncMock(return_value=(audit, debug))) as run_audit,
      patch.object(workflows, "_apply_module", new=tracking_apply_module),
    ):
      await workflows.apply_workflow(
        deepcopy(workflow_presets.PRESETS["scope-guard"]),
        chat,
        llm,
      )

    assert execution_order == SCOPE_GUARD_MODULE_ORDER
    assert diffscope.needs_diffscope(chat)
    assert autocheck.needs_autocheck(chat)
    revise.assert_awaited_once()
    run_audit.assert_awaited_once()
    assert llm.stream_final_completion.await_count == 1
    llm.emit_message.assert_any_await(revised_answer)

    history = chat.history()
    contents = [msg.get("content") or "" for msg in history]
    assert any("provided tools" in content for content in contents)
    assert any("outside the user's stated scope" in content for content in contents)
    assistant_contents = [
      msg.get("content") or ""
      for msg in history
      if msg.get("role") == "assistant"
    ]
    assert autocheck_draft in assistant_contents
    assert draft_with_violation not in assistant_contents


class TestResearchQuickWorkflowChain:
  @pytest.mark.asyncio
  async def test_research_quick_runs_tools_caveman_final_with_fetch(self):
    """research-quick: tools → caveman → final; fetch runs, autocheck skipped."""
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": RESEARCH_QUICK_USER_MESSAGE},
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
      return "Final research answer."

    llm.stream_final_completion = AsyncMock(side_effect=tracked_final)

    caveman_cheap = _cheap_llm_mock(
      AsyncMock(
        return_value={"queries": ["Stripe checkout session API response format 2024"]},
      )
    )

    with (
      request_context(),
      patch(
        "research.orchestrate.cheap_llm",
        return_value=caveman_cheap,
      ),
      patch("research.fetch.web_search", new=AsyncMock(return_value=MOCK_SEARCH_RESULT)) as web_search,
      patch("research.fetch.read_url", new=AsyncMock(return_value=MOCK_PAGE_CONTENT)) as read_url,
      patch.object(autocheck, "run_audit", new=AsyncMock()) as run_audit,
      patch.object(workflows, "_apply_module", new=tracking_apply_module),
    ):
      await workflows.apply_workflow(
        deepcopy(workflow_presets.PRESETS["research-quick"]),
        chat,
        llm,
      )

    assert execution_order == RESEARCH_QUICK_MODULE_ORDER
    assert await caveman.needs_research(chat, llm)
    assert not autocheck.needs_autocheck(chat)
    run_audit.assert_not_called()
    caveman_cheap.chat_completion.assert_awaited_once()
    web_search.assert_awaited_once()
    read_url.assert_awaited_once()
    assert llm.stream_final_completion.await_count == 1

    history = chat.history()
    contents = [msg.get("content") or "" for msg in history]
    assert any("provided tools" in content for content in contents)
    assert any("<research_brief>" in content for content in contents)


class TestResearchDeepWorkflowChain:
  @pytest.mark.asyncio
  async def test_research_deep_runs_tools_ponytail_final_two_hop(self):
    """research-deep: tools → ponytail → final; 2-hop research, caveman not in chain."""
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": RESEARCH_DEEP_USER_MESSAGE},
    ])
    llm = _make_llm()
    execution_order: list[str] = []
    real_apply_module = workflows._apply_module
    searched_queries: list[str] = []

    async def tracking_apply_module(module_name, module_cfg, chat_obj, llm_obj):
      execution_order.append(module_name)
      return await real_apply_module(module_name, module_cfg, chat_obj, llm_obj)

    async def tracked_final(**_kwargs):
      execution_order.append("final")
      llm.is_final_stream = True
      return "Final deep research answer."

    async def track_search(query: str, **_kwargs):
      searched_queries.append(query)
      return (
        MOCK_PONYTAIL_HOP2_SEARCH
        if len(searched_queries) > 2
        else MOCK_PONYTAIL_HOP1_SEARCH
      )

    llm.stream_final_completion = AsyncMock(side_effect=tracked_final)
    ponytail_cheap = _ponytail_cheap_llm_mock()

    original_early_exit = config.PONYTAIL_EARLY_EXIT_CHARS.__value__
    try:
      config.PONYTAIL_EARLY_EXIT_CHARS.__value__ = 15_000

      with (
        request_context(),
        patch(
          "research.orchestrate.cheap_llm",
          return_value=ponytail_cheap,
        ),
        patch(
          "research.fetch.web_search",
          new=AsyncMock(side_effect=track_search),
        ) as web_search,
        patch(
          "research.fetch.read_url",
          new=AsyncMock(return_value=MOCK_PONYTAIL_PAGE_CONTENT),
        ) as read_url,
        patch.object(autocheck, "run_audit", new=AsyncMock()) as run_audit,
        patch.object(workflows, "_apply_module", new=tracking_apply_module),
      ):
        await workflows.apply_workflow(
          deepcopy(workflow_presets.PRESETS["research-deep"]),
          chat,
          llm,
        )
    finally:
      config.PONYTAIL_EARLY_EXIT_CHARS.__value__ = original_early_exit

    assert execution_order == RESEARCH_DEEP_MODULE_ORDER
    assert "caveman" not in execution_order
    assert await ponytail.needs_research(chat, llm)
    assert not autocheck.needs_autocheck(chat)
    run_audit.assert_not_called()
    assert ponytail_cheap.chat_completion.await_count >= 3
    assert web_search.await_count >= 3
    read_url.assert_awaited()
    assert any(
      query in searched_queries
      for query in [
        "Django 5.0 release notes breaking changes",
        "django.utils.six removal django 5",
      ]
    )
    assert llm.stream_final_completion.await_count == 1

    history = chat.history()
    contents = [msg.get("content") or "" for msg in history]
    assert any("provided tools" in content for content in contents)
    assert any("<research_brief>" in content for content in contents)
    statuses = [call.args[0] for call in llm.emit_status.await_args_list]
    assert any("hop 1 (" in status for status in statuses)
    assert any("hop 2 (" in status for status in statuses)


class TestAgentResearchWorkflowChain:
  @pytest.mark.asyncio
  async def test_agent_research_runs_tools_caveman_final_with_fetch(self):
    """agent-research: tools → caveman → final; fetch runs, tools stay registered."""
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": AGENT_RESEARCH_USER_MESSAGE},
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
      return "Final agent-research answer."

    llm.stream_final_completion = AsyncMock(side_effect=tracked_final)

    caveman_cheap = _cheap_llm_mock(
      AsyncMock(
        return_value={
          "queries": ["Stripe checkout session API response format 2024"],
        },
      )
    )

    with (
      request_context(),
      patch(
        "research.orchestrate.cheap_llm",
        return_value=caveman_cheap,
      ),
      patch("research.fetch.web_search", new=AsyncMock(return_value=MOCK_SEARCH_RESULT)) as web_search,
      patch("research.fetch.read_url", new=AsyncMock(return_value=MOCK_PAGE_CONTENT)) as read_url,
      patch.object(autocheck, "run_audit", new=AsyncMock()) as run_audit,
      patch.object(workflows, "_apply_module", new=tracking_apply_module),
    ):
      await workflows.apply_workflow(
        deepcopy(workflow_presets.PRESETS["agent-research"]),
        chat,
        llm,
      )
      assert tool_registry.get_local_tool("web_search") is not None

    assert execution_order == AGENT_RESEARCH_MODULE_ORDER
    assert await caveman.needs_research(chat, llm)
    assert not autocheck.needs_autocheck(chat)
    run_audit.assert_not_called()
    caveman_cheap.chat_completion.assert_awaited_once()
    web_search.assert_awaited_once()
    read_url.assert_awaited_once()
    assert llm.stream_final_completion.await_count == 1

    history = chat.history()
    contents = [msg.get("content") or "" for msg in history]
    assert any("provided tools" in content for content in contents)
    assert any("<research_brief>" in content for content in contents)

  @pytest.mark.asyncio
  async def test_agent_research_skips_caveman_on_implementation_turn(self):
    """agent-research: tools → caveman → final; pure edit skips caveman fetch."""
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": AGENT_RESEARCH_IMPLEMENTATION_MESSAGE},
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
      return "Final implementation answer."

    llm.stream_final_completion = AsyncMock(side_effect=tracked_final)

    caveman_cheap = _cheap_llm_mock(AsyncMock())

    with (
      request_context(),
      patch(
        "research.orchestrate.cheap_llm",
        return_value=caveman_cheap,
      ),
      patch("research.fetch.web_search", new=AsyncMock()) as web_search,
      patch("research.fetch.read_url", new=AsyncMock()) as read_url,
      patch.object(autocheck, "run_audit", new=AsyncMock()) as run_audit,
      patch.object(workflows, "_apply_module", new=tracking_apply_module),
    ):
      await workflows.apply_workflow(
        deepcopy(workflow_presets.PRESETS["agent-research"]),
        chat,
        llm,
      )
      assert tool_registry.get_local_tool("web_search") is not None

    assert execution_order == AGENT_RESEARCH_MODULE_ORDER
    assert caveman.research_skip_reason(chat) == "implementation_turn"
    assert not await caveman.needs_research(chat, llm)
    assert not autocheck.needs_autocheck(chat)
    run_audit.assert_not_called()
    caveman_cheap.chat_completion.assert_not_called()
    web_search.assert_not_called()
    read_url.assert_not_called()
    assert llm.stream_final_completion.await_count == 1
    llm.emit_status.assert_any_await("Caveman research: skipped (implementation_turn)")

    history = chat.history()
    contents = [msg.get("content") or "" for msg in history]
    assert any("provided tools" in content for content in contents)
    assert not any("<research_brief>" in content for content in contents)


class TestAgentCodeWorkflowChain:
  @pytest.mark.asyncio
  async def test_agent_code_runs_full_chain_without_early_final(self):
    """agent-code must not stream final from sightline or diffscope mid-chain."""
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
    ])
    llm = _make_llm()
    execution_order: list[str] = []
    real_apply_module = workflows._apply_module

    async def tracking_apply_module(module_name, module_cfg, chat_obj, llm_obj):
      execution_order.append(module_name)
      return await real_apply_module(module_name, module_cfg, chat_obj, llm_obj)

    async def stream_final_side_effect(**_kwargs):
      execution_order.append("final")
      llm.is_final_stream = True
      return "Final agent-code answer."

    llm.stream_chat_completion = AsyncMock(return_value="Scoped draft.")
    llm.stream_final_completion = AsyncMock(side_effect=stream_final_side_effect)

    audit = autocheck.AuditResult(verdict="pass", summary="Looks good.")
    debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="pass")

    with (
      request_context(),
      patch(
        "research.orchestrate.cheap_llm",
        return_value=mock_autocheck_cheap_llm(draft_response="Autocheck draft."),
      ),
      patch.object(diffscope, "verify_workspace_paths", new=AsyncMock(return_value=[])),
      patch.object(autocheck, "gather_workspace_context", new=AsyncMock(return_value="")),
      patch.object(
        autocheck,
        "run_mechanical_preaudit",
        new=AsyncMock(return_value=("", [])),
      ),
      patch.object(autocheck, "run_audit", new=AsyncMock(return_value=(audit, debug))),
      patch.object(workflows, "_apply_module", new=tracking_apply_module),
    ):
      await workflows.apply_workflow(
        deepcopy(workflow_presets.PRESETS["agent-code"]),
        chat,
        llm,
      )

    assert execution_order == AGENT_CODE_MODULE_ORDER
    assert llm.stream_final_completion.await_count == 1

  @pytest.mark.asyncio
  async def test_agent_code_e2e_sightline_diffscope_autocheck(self):
    """agent-code E2E: sightline blocks writes, diffscope checks scope, autocheck audits."""
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": AGENT_CODE_USER_MESSAGE},
    ])
    llm = _make_llm()
    execution_order: list[str] = []
    real_apply_module = workflows._apply_module

    async def tracking_apply_module(module_name, module_cfg, chat_obj, llm_obj):
      execution_order.append(module_name)
      return await real_apply_module(module_name, module_cfg, chat_obj, llm_obj)

    draft_with_violation = (
      "Updated `src/foo.py` and `src/bar.py` for consistency."
    )
    revised_answer = "Only updated `src/foo.py`."
    autocheck_draft = "Scoped retry helper in `src/foo.py`."

    async def stream_final_side_effect(**_kwargs):
      execution_order.append("final")
      llm.is_final_stream = True
      return "Final agent-code answer."

    llm.stream_chat_completion = AsyncMock(return_value=draft_with_violation)
    llm.stream_final_completion = AsyncMock(side_effect=stream_final_side_effect)

    audit = autocheck.AuditResult(
      verdict="pass",
      summary="Retry helper looks correct.",
    )
    debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="pass")

    with (
      request_context(),
      patch(
        "research.orchestrate.cheap_llm",
        return_value=mock_autocheck_cheap_llm(draft_response=autocheck_draft),
      ),
      patch.object(diffscope, "verify_workspace_paths", new=AsyncMock(return_value=[])),
      patch.object(
        diffscope,
        "revise_with_correction",
        new=AsyncMock(return_value=revised_answer),
      ) as revise,
      patch.object(autocheck, "gather_workspace_context", new=AsyncMock(return_value="")),
      patch.object(
        autocheck,
        "run_mechanical_preaudit",
        new=AsyncMock(return_value=("", [])),
      ),
      patch.object(autocheck, "run_audit", new=AsyncMock(return_value=(audit, debug))) as run_audit,
      patch.object(workflows, "_apply_module", new=tracking_apply_module),
    ):
      await tools_module.write_file("blocked.txt", "seed")
      await workflows.apply_workflow(
        deepcopy(workflow_presets.PRESETS["agent-code"]),
        chat,
        llm,
      )

      write_tool = tool_registry.get_local_tool("write_file")
      assert getattr(write_tool, "_sightline_wrapped", False)

      with pytest.raises(ValueError, match="sightline_read_required"):
        await write_tool("blocked.txt", "unguarded edit")

    assert execution_order == AGENT_CODE_MODULE_ORDER
    assert diffscope.needs_diffscope(chat)
    assert autocheck.needs_autocheck(chat)
    revise.assert_awaited_once()
    run_audit.assert_awaited_once()
    assert llm.stream_final_completion.await_count == 1
    llm.emit_message.assert_any_await(revised_answer)

    history = chat.history()
    contents = [msg.get("content") or "" for msg in history]
    assert any("provided tools" in content for content in contents)
    assert any("outside the user's stated scope" in content for content in contents)
    assert any("read_file on the same path first" in content for content in contents)


class TestSightlineToolsComposition:
  @pytest.mark.asyncio
  async def test_sightline_after_tools_blocks_unguarded_write(self):
    """Module composition: sightline + tools blocks unguarded write."""
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Edit scratch notes carefully."},
    ])
    llm = _make_llm()

    async def tracked_final(**_kwargs):
      llm.is_final_stream = True
      return "Final answer."

    llm.stream_final_completion = AsyncMock(side_effect=tracked_final)

    workflow = {
      "id": "agent-scratch",
      "modules": [
        {"module": "tools", "config": {"final": False}},
        {"module": "sightline", "config": {"final": False}},
        "final",
      ],
    }

    with request_context():
      await tools_module.write_file("blocked.txt", "seed")
      await workflows.apply_workflow(deepcopy(workflow), chat, llm)

      write_tool = tool_registry.get_local_tool("write_file")
      assert getattr(write_tool, "_sightline_wrapped", False)

      with pytest.raises(ValueError, match="sightline_read_required"):
        await write_tool("blocked.txt", "unguarded edit")

      llm.emit_status.assert_awaited_once()
      assert "read_file required" in llm.emit_status.await_args.args[0]


class TestDiffscopeDeliverableChain:
  @pytest.mark.asyncio
  async def test_diffscope_scope_violation_triggers_revise(self):
    """diffscope + deliverable: scope violation triggers revise."""
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement the retry helper but only edit foo.py"},
    ])
    llm = _make_llm()

    draft_with_violation = (
      "Updated `src/foo.py` and `src/bar.py` for consistency."
    )
    revised_answer = "Only updated `src/foo.py`."

    async def draft_final(**kwargs):
      llm.is_final_stream = True
      return await llm.stream_chat_completion(**kwargs)

    llm.stream_final_completion = AsyncMock(side_effect=draft_final)
    llm.stream_chat_completion = AsyncMock(return_value=draft_with_violation)

    workflow = {
      "id": "scope-check",
      "modules": [
        {"module": "tools", "config": {"final": False}},
        "diffscope",
      ],
    }

    with (
      request_context(),
      patch.object(diffscope, "verify_workspace_paths", new=AsyncMock(return_value=[])),
      patch.object(
        diffscope,
        "revise_with_correction",
        new=AsyncMock(return_value=revised_answer),
      ) as revise,
      patch.object(workflows, "_apply_module", wraps=workflows._apply_module) as apply_module,
    ):
      await workflows.apply_workflow(deepcopy(workflow), chat, llm)

    applied = [call.args[0] for call in apply_module.await_args_list]
    assert applied == ["tools", "diffscope"]
    assert diffscope.needs_diffscope(chat)

    revise.assert_awaited_once()
    llm.emit_message.assert_awaited_once_with(revised_answer)

    history = chat.history()
    contents = [msg.get("content") or "" for msg in history]
    assert any("outside the user's stated scope" in content for content in contents)

  @pytest.mark.asyncio
  async def test_diffscope_collateral_disabled_blocks_extra_files_in_chain(self):
    """diffscope chain: hinted scope + ALLOW_COLLATERAL=false revises on extra files."""
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Update services/boost/src/utils.py to log errors."},
    ])
    llm = _make_llm()

    draft_with_extra = (
      "Updated `services/boost/src/utils.py` and `services/boost/src/config.py`."
    )
    revised_answer = "Only updated `services/boost/src/utils.py`."

    async def draft_final(**kwargs):
      llm.is_final_stream = True
      return await llm.stream_chat_completion(**kwargs)

    llm.stream_final_completion = AsyncMock(side_effect=draft_final)
    llm.stream_chat_completion = AsyncMock(return_value=draft_with_extra)

    workflow = {
      "id": "scope-check",
      "modules": [
        {"module": "tools", "config": {"final": False}},
        "diffscope",
      ],
    }

    original = config.DIFFSCOPE_ALLOW_COLLATERAL.__value__
    try:
      config.DIFFSCOPE_ALLOW_COLLATERAL.__value__ = False
      with (
        request_context(),
        patch.object(diffscope, "verify_workspace_paths", new=AsyncMock(return_value=[])),
        patch.object(
          diffscope,
          "revise_with_correction",
          new=AsyncMock(return_value=revised_answer),
        ) as revise,
        patch.object(workflows, "_apply_module", wraps=workflows._apply_module) as apply_module,
      ):
        await workflows.apply_workflow(deepcopy(workflow), chat, llm)
    finally:
      config.DIFFSCOPE_ALLOW_COLLATERAL.__value__ = original

    applied = [call.args[0] for call in apply_module.await_args_list]
    assert applied == ["tools", "diffscope"]
    revise.assert_awaited_once()
    llm.emit_message.assert_awaited_once_with(revised_answer)

    history = chat.history()
    contents = [msg.get("content") or "" for msg in history]
    assert any("outside the user's stated scope" in content for content in contents)


WORKFLOW_CHAIN_E2E_TEST_FILES = (
  Path(__file__).resolve(),
  Path(__file__).resolve().parent / "test_shipyard_workflow.py",
)


def _preset_ids_in_test_function(function: ast.AST) -> set[str]:
  preset_ids: set[str] = set()
  for node in ast.walk(function):
    if not isinstance(node, ast.Subscript):
      continue
    value = node.value
    if not (
      isinstance(value, ast.Attribute)
      and value.attr == "PRESETS"
      and isinstance(value.value, ast.Name)
      and value.value.id == "workflow_presets"
    ):
      continue
    if not isinstance(node.slice, ast.Constant) or not isinstance(node.slice.value, str):
      continue
    preset_ids.add(node.slice.value)
  return preset_ids


def _builtin_preset_chain_e2e_coverage() -> dict[str, list[str]]:
  """Map built-in preset IDs to chain/e2e test functions that exercise them."""
  coverage: dict[str, list[str]] = {}
  for test_file in WORKFLOW_CHAIN_E2E_TEST_FILES:
    tree = ast.parse(test_file.read_text(encoding="utf-8"), filename=str(test_file))
    for node in tree.body:
      if not isinstance(node, ast.ClassDef):
        continue
      for child in node.body:
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
          continue
        if not child.name.startswith("test_"):
          continue
        for preset_id in sorted(_preset_ids_in_test_function(child)):
          label = f"{test_file.stem}::{child.name}"
          coverage.setdefault(preset_id, []).append(label)
  return coverage


def _format_preset_chain_e2e_coverage_report(coverage: dict[str, list[str]]) -> str:
  lines = ["Built-in workflow preset chain/e2e coverage:"]
  for preset_id in sorted(workflow_presets.PRESETS):
    tests = coverage.get(preset_id, [])
    if tests:
      lines.append(f"  {preset_id}:")
      for test_name in tests:
        lines.append(f"    - {test_name}")
    else:
      lines.append(f"  {preset_id}: MISSING")
  return "\n".join(lines)


class TestBuiltinWorkflowPresetCoverage:
  def test_every_builtin_preset_has_chain_or_e2e_test(self):
    """Each built-in preset must be exercised in chain or shipyard e2e tests."""
    builtin_ids = set(workflow_presets.PRESETS)
    coverage = _builtin_preset_chain_e2e_coverage()
    missing = sorted(builtin_ids - set(coverage))
    assert not missing, (
      "Built-in workflow presets without chain/e2e tests in "
      "test_agentic_workflow_chains.py or test_shipyard_workflow.py: "
      f"{', '.join(missing)}\n"
      f"{_format_preset_chain_e2e_coverage_report(coverage)}"
    )