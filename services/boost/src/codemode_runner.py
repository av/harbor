"""Child process for the `codemode` module.

Reads one JSON line describing the program and the tool names it may call,
executes the program with a stub per tool, and writes a final JSON line with
the `result` variable and any traceback.

Protocol lines travel on the real stdout; the program's own `print()` output is
tee'd into `{"stdout": ...}` lines so it can never corrupt the channel and so a
program killed on timeout still reports what it printed before dying.
"""

import io
import json
import sys
import traceback

PROGRAM_FILENAME = "<codemode>"


def _emit(channel, message):
  channel.write(json.dumps(message, ensure_ascii=False, default=repr) + "\n")
  channel.flush()


def _cap(text, max_output):
  if max_output > 0 and len(text) > max_output:
    return text[:max_output] + f"\n...[truncated to {max_output} chars]"
  return text


def _safe_result(value, max_output):
  """JSON-safe, size-bounded rendering of the program's `result` variable."""
  if value is None or isinstance(value, (int, float, bool)):
    return value
  if isinstance(value, str):
    return _cap(value, max_output)

  try:
    encoded = json.dumps(value, ensure_ascii=False, default=repr)
  except (TypeError, ValueError):
    return _cap(repr(value), max_output)

  if max_output > 0 and len(encoded) > max_output:
    return _cap(encoded, max_output)
  return value


class _Tee(io.TextIOBase):
  """Program stdout: buffered per line and streamed to the host, up to a cap."""

  def __init__(self, channel, max_output):
    self.channel = channel
    self.max_output = max_output
    self.pending = ""
    self.sent = 0
    self.marked = False

  def writable(self) -> bool:
    return True

  def write(self, text) -> int:
    if not isinstance(text, str):
      text = str(text)
    self.pending += text
    while "\n" in self.pending:
      chunk, self.pending = self.pending.split("\n", 1)
      self._send(chunk + "\n")
    if self.max_output > 0 and len(self.pending) > self.max_output:
      self._send(self.pending)
      self.pending = ""
    return len(text)

  def _send(self, chunk):
    if self.max_output > 0:
      remaining = self.max_output - self.sent
      dropped = len(chunk) > remaining
      chunk = chunk[:max(remaining, 0)]
      if chunk:
        self.sent += len(chunk)
        _emit(self.channel, {"stdout": chunk})
      if dropped and not self.marked:
        self.marked = True
        _emit(
          self.channel,
          {"stdout": f"\n...[truncated to {self.max_output} chars]"},
        )
      return
    self.sent += len(chunk)
    _emit(self.channel, {"stdout": chunk})

  def flush(self) -> None:
    if self.pending:
      self._send(self.pending)
      self.pending = ""


def _make_stub(name, params, channel):
  def stub(*args, **kwargs):
    bound = dict(kwargs)
    for index, value in enumerate(args):
      if index >= len(params):
        raise TypeError(
          f"{name}() takes at most {len(params)} positional argument(s)"
        )
      bound[params[index]] = value

    _emit(channel, {"call": name, "args": bound})
    line = sys.stdin.readline()
    if not line:
      raise RuntimeError(f"{name}: host closed the connection")

    reply = json.loads(line)
    if "error" in reply and reply["error"] is not None:
      raise RuntimeError(reply["error"])
    return reply.get("result")

  stub.__name__ = name
  stub.__qualname__ = name
  return stub


def _program_traceback(exc: BaseException) -> str:
  """Format a traceback with the runner's own frames removed."""
  frames = [
    frame for frame in traceback.extract_tb(exc.__traceback__)
    if frame.filename != __file__
  ]
  lines = ["Traceback (most recent call last):\n"]
  lines.extend(traceback.StackSummary.from_list(frames).format())
  lines.extend(traceback.format_exception_only(type(exc), exc))
  return "".join(lines)


def main() -> int:
  channel = sys.stdout
  first_line = sys.stdin.readline()
  if not first_line:
    return 1

  request = json.loads(first_line)
  code = request.get("code", "")
  params = request.get("params", {})
  max_output = int(request.get("max_output") or 0)

  scope = {"__name__": "__main__"}
  for name in request.get("tools", []):
    scope[name] = _make_stub(name, params.get(name, []), channel)

  tee = _Tee(channel, max_output)
  sys.stdout = tee
  error = None
  try:
    exec(compile(code, PROGRAM_FILENAME, "exec"), scope)
  except BaseException as exc:  # noqa: BLE001 - reported back to the model
    error = _cap(_program_traceback(exc), max_output)
  finally:
    sys.stdout = channel
    tee.flush()

  _emit(
    channel, {
      "done": True,
      "result": _safe_result(scope.get("result"), max_output),
      "error": error,
    }
  )
  return 0


if __name__ == "__main__":
  sys.exit(main())
