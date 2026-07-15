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
import config
import tools.registry as tool_registry
import workflows
from middleware.request_id import request_id_var
from modules import autocheck, diffscope
from modules import tools as tools_module
from state import request as request_state


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

  @pytest.mark.asyncio
  async def test_diffscope_allowed_only_revises_despite_collateral_enabled(self):
    """diffscope chain: only-edit scope blocks extra files even when collateral is allowed."""
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper but only edit src/foo.py"},
    ])
    llm = _make_llm()

    draft_with_extra = (
      "Updated `src/foo.py` and `src/bar.py` for consistency."
    )
    revised_answer = "Only updated `src/foo.py`."

    async def draft_final(**kwargs):
      llm.is_final_stream = True
      return await llm.stream_chat_completion(**kwargs)

    llm.stream_final_completion = AsyncMock(side_effect=draft_final)
    llm.stream_chat_completion = AsyncMock(return_value=draft_with_extra)

    workflow = {
      "id": "allowed-only-check",
      "modules": [
        {"module": "tools", "config": {"final": False}},
        "diffscope",
      ],
    }

    original = config.DIFFSCOPE_ALLOW_COLLATERAL.__value__
    try:
      config.DIFFSCOPE_ALLOW_COLLATERAL.__value__ = True
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

    scope = diffscope.extract_user_scope(chat)
    assert scope.allowed_only
    applied = [call.args[0] for call in apply_module.await_args_list]
    assert applied == ["tools", "diffscope"]
    revise.assert_awaited_once()
    llm.emit_message.assert_awaited_once_with(revised_answer)

    statuses = [call.args[0] for call in llm.emit_status.await_args_list]
    assert not any("collateral" in status.lower() for status in statuses)

    history = chat.history()
    contents = [msg.get("content") or "" for msg in history]
    assert any("outside the user's stated scope" in content for content in contents)
