"""Integration tests for agentic workflow chains with mocked LLM."""

import os
import sys
import uuid
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chat as ch
import tools.registry as tool_registry
import workflows
from middleware.request_id import request_id_var
from modules import autocheck, caveman, diffscope, sightline
from modules import tools as tools_module
from modules import workflows as workflow_presets
from state import request as request_state


CODE_CHECK_MODULE_ORDER = ["tools", "autocheck", "final"]
SCOPE_GUARD_MODULE_ORDER = ["tools", "diffscope", "autocheck", "final"]
RESEARCH_QUICK_MODULE_ORDER = ["tools", "caveman", "final"]

CODE_CHECK_USER_MESSAGE = (
  "Implement retry helper with exponential backoff in services/boost/src/utils.py"
)

SCOPE_GUARD_USER_MESSAGE = (
  "Fix the bug in services/boost/src/utils.py only — do not touch other files"
)

SCOPE_GUARD_VIOLATION_USER_MESSAGE = (
  "Fix the bug but only edit src/foo.py — do not touch other files"
)

RESEARCH_QUICK_USER_MESSAGE = (
  "What is the Stripe checkout session API endpoint response format in 2024?"
)

MOCK_SEARCH_RESULT = (
  "1. [Stripe Checkout API](https://docs.stripe.com/checkout) (Date: N/A)\n"
  "Checkout session response includes id, url, and status fields."
)
MOCK_PAGE_CONTENT = "Stripe checkout session API reference for 2024-06-20."


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

    llm.stream_chat_completion = AsyncMock(
      side_effect=[draft_with_violation, autocheck_draft],
    )
    llm.stream_final_completion = AsyncMock(side_effect=stream_final_side_effect)

    audit = autocheck.AuditResult(verdict="pass", summary="Scoped fix looks correct.")
    debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="pass")

    with (
      request_context(),
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


class TestResearchQuickWorkflowChain:
  @pytest.mark.asyncio
  async def test_research_quick_runs_tools_caveman_final_with_fetch(self):
    """research-quick: tools → caveman → final; research question triggers fetch."""
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
      patch.object(workflows, "_apply_module", new=tracking_apply_module),
    ):
      await workflows.apply_workflow(
        deepcopy(workflow_presets.PRESETS["research-quick"]),
        chat,
        llm,
      )

    assert execution_order == RESEARCH_QUICK_MODULE_ORDER
    assert await caveman.needs_research(chat, llm)
    caveman_cheap.chat_completion.assert_awaited_once()
    web_search.assert_awaited_once()
    read_url.assert_awaited_once()
    assert llm.stream_final_completion.await_count == 1

    history = chat.history()
    contents = [msg.get("content") or "" for msg in history]
    assert any("provided tools" in content for content in contents)
    assert any("<research_brief>" in content for content in contents)


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

    llm.stream_chat_completion = AsyncMock(
      side_effect=["Scoped draft.", "Autocheck draft."],
    )
    llm.stream_final_completion = AsyncMock(side_effect=stream_final_side_effect)

    audit = autocheck.AuditResult(verdict="pass", summary="Looks good.")
    debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="pass")

    with (
      request_context(),
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

    assert execution_order == ["tools", "sightline", "diffscope", "autocheck", "final"]
    assert llm.stream_final_completion.await_count == 1


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