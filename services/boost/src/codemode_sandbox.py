"""Host side of the `codemode` sandbox.

Spawns `codemode_runner.py` in an isolated interpreter, feeds it the program
plus the names of the hidden local tools, and services every tool call the
program makes over a JSON-lines channel.

This is process isolation, not a security boundary: the child shares Boost's
filesystem and network.
"""

import asyncio
import contextlib
import inspect
import json
import os
import signal
import sys
from pathlib import Path

import log
from tools.registry import LOCAL_TOOL_PREFIX

logger = log.setup_logger("codemode")

RUNNER_PATH = Path(__file__).with_name("codemode_runner.py")

STDERR_CAP = 4096
CLEANUP_TIMEOUT = 1.0
DEFAULT_MAX_OUTPUT = 8000


def effective_max_output(max_output: int) -> int:
  """A non-positive cap means "use the default", never "unlimited"."""
  return max_output if max_output > 0 else DEFAULT_MAX_OUTPUT


def truncate(text: str, max_chars: int) -> str:
  if max_chars > 0 and len(text) > max_chars:
    return text[:max_chars] + f"\n...[truncated to {max_chars} chars]"
  return text


def tool_params(fn) -> list[str]:
  """Positional parameter order of a local tool, for positional stub calls."""
  try:
    return list(inspect.signature(fn).parameters)
  except (TypeError, ValueError):
    return []


def _encode(value):
  """Make a tool result JSON-safe without losing plain strings."""
  if isinstance(value, (str, int, float, bool)) or value is None:
    return value
  try:
    json.dumps(value)
  except (TypeError, ValueError):
    return repr(value)
  return value


async def _invoke(fn, args: dict):
  result = fn(**args)
  if inspect.iscoroutinefunction(fn):
    result = await result
  return result


async def _drain(stream, cap: int) -> bytes:
  """Keep the child's stderr pipe empty, remembering only the first `cap` bytes."""
  kept = bytearray()
  while True:
    chunk = await stream.read(8192)
    if not chunk:
      break
    if len(kept) < cap:
      kept.extend(chunk[:cap - len(kept)])
  return bytes(kept)


async def _stderr_text(task) -> str:
  """Whatever the drain task collected, best effort."""
  try:
    collected = await asyncio.wait_for(asyncio.shield(task), CLEANUP_TIMEOUT)
  except Exception:  # noqa: BLE001 - stderr is a diagnostic, never a failure
    return ""
  return collected.decode("utf-8", errors="replace").strip()


async def _exchange(
  proc, code, hidden_tools, max_calls, max_output, captured, stderr_task
):
  names = [key[len(LOCAL_TOOL_PREFIX):] for key in hidden_tools]
  params = {
    key[len(LOCAL_TOOL_PREFIX):]: tool_params(fn)
    for key, fn in hidden_tools.items()
  }

  proc.stdin.write(
    (
      json.dumps(
        {
          "code": code,
          "tools": names,
          "params": params,
          "max_output": max_output,
        },
        ensure_ascii=False,
      ) + "\n"
    ).encode("utf-8")
  )
  await proc.stdin.drain()

  calls = 0
  while True:
    line = await proc.stdout.readline()
    if not line:
      stderr = await _stderr_text(stderr_task)
      return {
        "stdout": captured["stdout"],
        "result": None,
        "error": f"runner exited unexpectedly: {stderr or 'no output'}",
      }

    try:
      message = json.loads(line.decode("utf-8"))
    except json.JSONDecodeError:
      return {
        "stdout": captured["stdout"],
        "result": None,
        "error": f"malformed runner message: {line.decode('utf-8', errors='replace').strip()}",
      }

    if "stdout" in message and not message.get("done"):
      captured["stdout"] += message["stdout"] or ""
      continue

    if message.get("done"):
      return {
        "stdout": captured["stdout"],
        "result": message.get("result"),
        "error": message.get("error"),
      }

    name = message.get("call")
    args = message.get("args") or {}
    calls += 1

    if calls > max_calls:
      reply = {"error": f"call limit {max_calls} reached"}
    else:
      fn = hidden_tools.get(LOCAL_TOOL_PREFIX + str(name))
      if fn is None:
        reply = {"error": f"unknown tool: {name}"}
      else:
        try:
          reply = {"result": _encode(await _invoke(fn, args))}
        except Exception as exc:  # noqa: BLE001 - surfaced inside the program
          reply = {"error": f"{type(exc).__name__}: {exc}"}

    proc.stdin.write(
      (json.dumps(reply, ensure_ascii=False, default=str) + "\n").encode("utf-8")
    )
    await proc.stdin.drain()


async def run(
  code: str,
  hidden_tools: dict,
  *,
  timeout: int,
  max_output: int,
  max_calls: int,
) -> dict:
  """Run `code` in the sandbox, returning `{stdout, result, error}`."""
  captured = {"stdout": ""}
  max_output = effective_max_output(max_output)

  try:
    proc = await asyncio.create_subprocess_exec(
      sys.executable,
      "-I",
      "-S",
      str(RUNNER_PATH),
      stdin=asyncio.subprocess.PIPE,
      stdout=asyncio.subprocess.PIPE,
      stderr=asyncio.subprocess.PIPE,
      start_new_session=True,
      limit=max(4 * max_output, 1 << 20),
    )
  except OSError as exc:
    return {"stdout": "", "result": None, "error": f"failed to start sandbox: {exc}"}

  stderr_task = asyncio.ensure_future(_drain(proc.stderr, STDERR_CAP))
  failed = True

  try:
    outcome = await asyncio.wait_for(
      _exchange(
        proc, code, hidden_tools, max_calls, max_output, captured, stderr_task
      ),
      timeout=timeout,
    )
    failed = False
  except asyncio.TimeoutError:
    logger.warning(f"codemode: program exceeded {timeout}s, killing sandbox")
    outcome = {
      "stdout": captured["stdout"],
      "result": None,
      "error": f"timeout after {timeout}s",
    }
  except Exception as exc:  # noqa: BLE001 - never raises into the tool loop
    outcome = {
      "stdout": captured["stdout"],
      "result": None,
      "error": f"sandbox failure: {type(exc).__name__}: {exc}",
    }
  finally:
    await _cleanup(proc, stderr_task, force=failed)

  outcome["stdout"] = truncate(outcome.get("stdout") or "", max_output)
  return outcome


async def _cleanup(proc, stderr_task, *, force: bool) -> None:
  """Let go of the runner and its pipes, without blocking.

  A program that finished on its own gets a short window to exit by itself,
  then the whole process group is SIGKILLed either way: the runner may have
  exited leaving children of its own behind, and those must not outlive it.
  """
  if proc.returncode is None and not force:
    with contextlib.suppress(Exception):
      proc.stdin.close()
    with contextlib.suppress(Exception):
      await asyncio.wait_for(asyncio.shield(proc.wait()), CLEANUP_TIMEOUT)

  # start_new_session makes the runner its own group leader, so the pgid is
  # its pid - which stays usable after the leader itself has been reaped.
  with contextlib.suppress(ProcessLookupError):
    os.killpg(proc.pid, signal.SIGKILL)

  if proc.returncode is None:
    with contextlib.suppress(Exception):
      await asyncio.wait_for(asyncio.shield(proc.wait()), CLEANUP_TIMEOUT)

  # Closing first gives the drain EOF even when a grandchild outside the
  # process group still holds the write end of the pipe.
  transport = getattr(proc, "_transport", None)
  if transport is not None:
    with contextlib.suppress(Exception):
      transport.close()

  stderr_task.cancel()
  # CancelledError is a BaseException: suppressing only Exception here would
  # cancel the caller's request instead of returning the outcome.
  with contextlib.suppress(BaseException):
    await stderr_task
