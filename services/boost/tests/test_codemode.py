"""Unit tests for the codemode Boost module."""

import os
import subprocess
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chat as ch
import codemode_sandbox
import config
import tools.registry as tool_registry
from modules import codemode
from state import request as request_state
from tools.registry import LOCAL_TOOL_PREFIX


@contextmanager
def request_context():
  req = MagicMock()
  req.state = type("State", (), {})()
  token_req = request_state.set(req)
  try:
    yield req
  finally:
    request_state.reset(token_req)
    for attribute in ("local_tools", "hidden_local_tools"):
      if hasattr(req.state, attribute):
        delattr(req.state, attribute)


@contextmanager
def config_overrides(**overrides):
  saved = {key: getattr(config, key).__value__ for key in overrides}
  for key, value in overrides.items():
    getattr(config, key).__value__ = value
  try:
    yield
  finally:
    for key, value in saved.items():
      getattr(config, key).__value__ = value


def make_chat(content: str = "What time is it in Warsaw?") -> ch.Chat:
  return ch.Chat.from_conversation([{"role": "user", "content": content}])


def make_llm(on_final=None):
  llm = MagicMock()
  llm.boost_params = {}

  async def _final():
    if on_final is not None:
      return on_final()
    return "final"

  llm.stream_final_completion = _final
  return llm


def system_messages(chat: ch.Chat) -> list[str]:
  return [
    message["content"] for message in chat.history() if message["role"] == "system"
  ]


async def failing_tool() -> str:
  """
  Always raises so error propagation can be observed.
  """
  raise ValueError("nope")


async def echo_tool(value: str = "x") -> str:
  """
  Echo the given value back.

  Args:
    value (str): Value to echo.
  """
  return value * 100


class TestAdvertisedTools:
  @pytest.mark.asyncio
  async def test_advertises_single_tool(self):
    seen = {}

    with request_context(), config_overrides(TOOLS=["current_time", "add_note", "finish"]):
      chat = make_chat()
      llm = make_llm(on_final=lambda: seen.update(defs=tool_registry.collect_tool_defs()))
      await codemode.apply(chat, llm, {})

    defs = seen["defs"]
    assert len(defs) == 1
    assert defs[0]["function"]["name"] == "__tool_execute_code"
    assert list(defs[0]["function"]["parameters"]["properties"]) == ["code"]

  @pytest.mark.asyncio
  async def test_catalog_absorbs(self):
    async def earlier_step_tool(query: str) -> str:
      """
      Registered by an earlier workflow step.

      Args:
        query (str): Anything.
      """
      return query

    with request_context(), config_overrides(TOOLS=["current_time", "finish"]):
      tool_registry.set_local_tool("earlier_step_tool", earlier_step_tool)
      hidden = codemode.hide(codemode.catalog({}))

      assert set(hidden) == {
        LOCAL_TOOL_PREFIX + "current_time",
        LOCAL_TOOL_PREFIX + "finish",
        LOCAL_TOOL_PREFIX + "earlier_step_tool",
      }
      assert [
        item["function"]["name"] for item in tool_registry.collect_tool_defs()
      ] == [LOCAL_TOOL_PREFIX + "execute_code"]
      assert set(tool_registry.get_local_tools()) == set(hidden) | {
        LOCAL_TOOL_PREFIX + "execute_code"
      }

  @pytest.mark.asyncio
  async def test_direct_call_of_hidden_tool_executes_server_side(self):
    """A model that calls a hidden tool by name is served by Boost, not the client."""
    with request_context(), config_overrides(TOOLS=["current_time", "finish"]):
      codemode.hide(codemode.catalog({}))

      # The exact branch `llm.py` takes for every incoming tool call.
      for name in ("current_time", "finish", "__tool_current_time"):
        assert tool_registry.is_local_tool(name), (
          f"{name} would be passed back to the API client"
        )

      stamp = await tool_registry.call_local_tool("current_time", timezone="UTC")
      answer = await tool_registry.call_local_tool("finish", answer="done")

      assert "T" in stamp
      assert "done" in answer
      assert [
        item["function"]["name"] for item in tool_registry.collect_tool_defs()
      ] == [LOCAL_TOOL_PREFIX + "execute_code"]

  @pytest.mark.asyncio
  async def test_client_tools_untouched(self):
    import llm as llm_mod

    client_tool = {
      "type": "function",
      "function": {"name": "client_side_lookup", "parameters": {}},
    }

    with request_context(), config_overrides(TOOLS=["current_time"]):
      backend = llm_mod.LLM.__new__(llm_mod.LLM)
      backend.model = "test-model"
      backend.params = {"tools": [client_tool]}

      hidden = codemode.hide(codemode.catalog({}))
      params = await backend.resolve_request_params()

      names = [tool["function"]["name"] for tool in params["tools"]]
      assert names == ["client_side_lookup", "__tool_execute_code"]
      assert LOCAL_TOOL_PREFIX + "client_side_lookup" not in hidden
      assert "client_side_lookup" not in codemode.render_prompt(hidden)


class TestPrompt:
  @pytest.mark.asyncio
  async def test_prompt_renders_signatures(self):
    with request_context(), config_overrides(TOOLS=["current_time", "finish"]):
      chat = make_chat()
      await codemode.apply(chat, make_llm(), {})

    prompt = "\n".join(system_messages(chat))
    assert "current_time(timezone: str = 'UTC') -> str" in prompt
    assert "Return the current date and time in a named timezone." in prompt
    assert "finish(answer: str) -> str" in prompt
    assert "execute_code(code)" in prompt
    assert "The functions above are not tools." in prompt
    assert "print(...)" in prompt
    assert "result" in prompt


class TestExecution:
  @pytest.mark.asyncio
  async def test_roundtrip(self):
    with request_context(), config_overrides(TOOLS=["current_time"]):
      codemode.hide(codemode.catalog({}))
      output = await codemode.execute_code(
        "stamp = current_time('UTC')\n"
        "print('now:', stamp)\n"
        "result = len(stamp) > 0\n"
      )

    assert output.startswith("now: ")
    assert "T" in output
    assert "result: True" in output
    assert "error:" not in output

  @pytest.mark.asyncio
  async def test_timeout_kills(self):
    with request_context(), config_overrides(TOOLS=["current_time"], CODEMODE_TIMEOUT=1):
      codemode.hide(codemode.catalog({}))
      output = await codemode.execute_code("while True:\n  pass\n")

    assert "error: timeout after 1s" in output

  @pytest.mark.asyncio
  async def test_program_error(self):
    with request_context(), config_overrides(TOOLS=["current_time"]):
      codemode.hide(codemode.catalog({}))
      tool_registry.set_local_tool("failing_tool", failing_tool)
      tool_registry.hide_local_tool("failing_tool")

      crash = await codemode.execute_code("raise ValueError('boom')")
      caught = await codemode.execute_code(
        "try:\n"
        "  failing_tool()\n"
        "except RuntimeError as exc:\n"
        "  print('caught', exc)\n"
      )

      assert "Traceback (most recent call last):" in crash
      assert "ValueError: boom" in crash
      assert '<codemode>' in crash
      assert "caught ValueError: nope" in caught

      # The tool loop keeps working after both failures.
      assert [
        item["function"]["name"] for item in tool_registry.collect_tool_defs()
      ] == [LOCAL_TOOL_PREFIX + "execute_code"]

  @pytest.mark.asyncio
  async def test_output_and_call_caps(self):
    with request_context(), config_overrides(TOOLS=["current_time"], CODEMODE_MAX_CALLS=2):
      codemode.hide(codemode.catalog({}))
      tool_registry.set_local_tool("echo_tool", echo_tool)
      tool_registry.hide_local_tool("echo_tool")

      with config_overrides(CODEMODE_MAX_OUTPUT=50):
        capped = await codemode.execute_code("print('x' * 500)")

      limited = await codemode.execute_code(
        "for i in range(4):\n"
        "  try:\n"
        "    echo_tool('a')\n"
        "    print(i, 'ok')\n"
        "  except RuntimeError as exc:\n"
        "    print(i, exc)\n"
      )

    assert "...[truncated to 50 chars]" in capped
    assert len(capped.split("\n")[0]) == 50
    assert "0 ok" in limited and "1 ok" in limited
    assert "2 call limit 2 reached" in limited
    assert "3 call limit 2 reached" in limited


  @pytest.mark.asyncio
  async def test_output_cap_large_line(self):
    """Output far past the reader's line limit degrades to truncated text."""
    with request_context(), config_overrides(
      TOOLS=["current_time"], CODEMODE_MAX_OUTPUT=200
    ):
      codemode.hide(codemode.catalog({}))

      printed = await codemode.execute_code("print('y' * 5_000_000)")
      returned = await codemode.execute_code("result = 'r' * 100000")
      structured = await codemode.execute_code("result = ['z' * 1000] * 500")

    for output in (printed, returned, structured):
      assert "sandbox failure" not in output
      assert "...[truncated to 200 chars]" in output
      assert len(output) < 1000

  @pytest.mark.asyncio
  async def test_timeout_grandchild_and_stderr(self):
    """Neither a stderr flood nor an orphan grandchild can outlive the timeout."""
    import time

    with request_context(), config_overrides(
      TOOLS=["current_time"], CODEMODE_TIMEOUT=2
    ):
      codemode.hide(codemode.catalog({}))

      started = time.monotonic()
      flooded = await codemode.execute_code(
        "import sys\n"
        "print('before the flood')\n"
        "sys.stderr.write('e' * 300_000)\n"
        "while True:\n"
        "  pass\n"
      )
      flood_elapsed = time.monotonic() - started

      started = time.monotonic()
      spawned = await codemode.execute_code(
        "import subprocess\n"
        "subprocess.Popen(['sleep', '31337'])\n"
        "while True:\n"
        "  pass\n"
      )
      spawn_elapsed = time.monotonic() - started

      # Escapes the process group, so it keeps the runner's pipes open past
      # the kill - the caller must still get the timeout string back.
      started = time.monotonic()
      escaped = await codemode.execute_code(
        "import subprocess\n"
        "subprocess.Popen(['sleep', '31338'], start_new_session=True)\n"
        "while True:\n"
        "  pass\n"
      )
      escape_elapsed = time.monotonic() - started

    assert "error: timeout after 2s" in flooded
    assert "before the flood" in flooded  # partial stdout survives the kill
    assert "error: timeout after 2s" in spawned
    assert "error: timeout after 2s" in escaped
    assert flood_elapsed < 4
    assert spawn_elapsed < 4
    assert escape_elapsed < 4

    # The escaped grandchild is out of the group by construction, so it is the
    # test's job to reap it.
    subprocess.run(["pkill", "-f", "sleep 31338"])

    # Exact argv match: this session's own command line mentions the repro.
    running = subprocess.run(["ps", "-eo", "args="], capture_output=True, text=True)
    assert "sleep 31337" not in [
      line.strip() for line in running.stdout.splitlines()
    ]

    zombies = subprocess.run(
      ["ps", "-o", "stat=", "--ppid", str(os.getpid())],
      capture_output=True,
      text=True,
    )
    assert "Z" not in zombies.stdout

  @pytest.mark.asyncio
  async def test_clean_exit_kills_in_group_child(self):
    """A child left behind by a program that exits normally dies with the group."""
    import time

    with request_context(), config_overrides(TOOLS=["current_time"]):
      codemode.hide(codemode.catalog({}))

      started = time.monotonic()
      done = await codemode.execute_code(
        "import subprocess\n"
        "subprocess.Popen(['sleep', '302'])\n"
        "print('done')\n"
      )
      elapsed = time.monotonic() - started

    assert "done" in done
    assert elapsed < 1.5

    running = subprocess.run(["ps", "-eo", "args="], capture_output=True, text=True)
    assert "sleep 302" not in [line.strip() for line in running.stdout.splitlines()]


class TestRegistryLifecycle:
  @pytest.mark.asyncio
  async def test_restores_registry(self):
    expected = {
      LOCAL_TOOL_PREFIX + "current_time",
      LOCAL_TOOL_PREFIX + "finish",
    }

    with request_context(), config_overrides(TOOLS=["current_time", "finish"]):
      await codemode.apply(make_chat(), make_llm(), {})
      assert set(tool_registry.get_local_tools()) == expected

    def _boom():
      raise RuntimeError("backend down")

    with request_context(), config_overrides(TOOLS=["current_time", "finish"]):
      with pytest.raises(RuntimeError):
        await codemode.apply(make_chat(), make_llm(on_final=_boom), {})
      assert set(tool_registry.get_local_tools()) == expected

    with request_context(), config_overrides(
      TOOLS=["current_time", "finish"],
      CODEMODE_TIMEOUT=1,
    ):
      hidden = codemode.hide(codemode.catalog({}))
      timed_out = await codemode.execute_code("while True:\n  pass\n")
      assert "timeout" in timed_out
      codemode.restore(hidden)
      assert set(tool_registry.get_local_tools()) == expected


  @pytest.mark.asyncio
  async def test_restore_readvertises_hidden_tools(self):
    """Unwinding clears the hidden marks, not just the registry contents."""
    with request_context(), config_overrides(TOOLS=["current_time", "finish"]):
      hidden = codemode.hide(codemode.catalog({}))
      assert tool_registry.is_hidden_local_tool("current_time")

      codemode.restore(hidden)

      assert tool_registry.get_hidden_tool_names() == set()
      assert sorted(
        item["function"]["name"] for item in tool_registry.collect_tool_defs()
      ) == [LOCAL_TOOL_PREFIX + "current_time", LOCAL_TOOL_PREFIX + "finish"]

  @pytest.mark.asyncio
  async def test_defer_final_keeps_execute_code(self):
    """A deferred final still sees only `execute_code` after apply returns."""
    with request_context(), config_overrides(TOOLS=["current_time", "finish"]):
      await codemode.apply(make_chat(), make_llm(), {"defer_final": True})

      defs = tool_registry.collect_tool_defs()
      assert [item["function"]["name"] for item in defs] == ["__tool_execute_code"]


class TestConfiguration:
  def test_empty_env_uses_defaults(self):
    """Compose injects "" when .env predates the module; Boost must still boot."""
    from config import Config

    knobs = [
      config.CODEMODE_TIMEOUT,
      config.CODEMODE_MAX_OUTPUT,
      config.CODEMODE_MAX_CALLS,
    ]

    with patch.dict(os.environ, {knob.name: "" for knob in knobs}, clear=False):
      for knob in knobs:
        fresh = Config[int](name=knob.name, type=int, default=knob.default)
        assert fresh.value == int(knob.default)


class TestSandboxHelpers:
  def test_truncate_is_noop_under_cap(self):
    assert codemode_sandbox.truncate("abc", 10) == "abc"

  def test_render_signature_optional_types(self):
    parameters = {
      "properties": {
        "pattern": {"type": "string"},
        "glob": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
        "max_matches": {"type": "integer", "default": 5},
      },
      "required": ["pattern"],
    }
    assert codemode.render_signature("grep_workspace", parameters) == (
      "grep_workspace(pattern: str, glob: str | None = None, max_matches: int = 5) -> str"
    )
