#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["textual>=0.89"]
# ///
"""Scripted demo for `harbor launch`.

The default mode is a narrated terminal story. The full-screen Textual
dashboard is available with --tui for captures where a dashboard helps.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field


DEFAULT_BACKEND = "llamacpp"
DEFAULT_TOOL = "mi"
DEFAULT_TASK = "Explain what harbor launch does in one sentence."
DEFAULT_WEB_TASK = (
    "Use web search to find one current fact about local LLM tools, "
    "then answer in one sentence."
)
SUPPORTED_TOOLS = ("codex", "grok", "hermes", "mi", "opencode", "pi")


@dataclass
class Args:
    backend: str
    model: str
    tool: str
    task: str
    web_task: str
    allow_missing_tool: bool
    dry_run: bool
    record: str
    capture_mode: str
    duration: int
    yes: bool
    tui: bool


@dataclass
class DemoStep:
    title: str
    commands: list[list[str]] = field(default_factory=list)
    proves: str = ""
    why: str = ""
    look_for: str = ""
    explanation: str = ""
    skip_when_tool_missing: bool = False
    skip_command_indexes_when_tool_missing: tuple[int, ...] = ()
    status: str = "PENDING"


def quote_cmd(args: list[str]) -> str:
    return " ".join(shlex.quote(arg) for arg in args)


def display_command(args: list[str]) -> str:
    return quote_cmd(args)


def resolve_harbor_bin() -> str:
    if shutil.which("harbor"):
        return "harbor"
    if os.path.isfile("./harbor.sh") and os.access("./harbor.sh", os.X_OK):
        return "./harbor.sh"
    return "harbor"


def execution_command(args: list[str], harbor_bin: str) -> list[str]:
    if args and args[0] == "harbor":
        return [harbor_bin, *args[1:]]
    return args


def tool_label(tool: str) -> str:
    return {
        "codex": "OpenAI Codex",
        "grok": "Grok",
        "hermes": "Hermes",
        "mi": "mi",
        "opencode": "OpenCode",
        "pi": "pi",
    }.get(tool, tool)


def prompt_args(tool: str, prompt: str) -> list[str]:
    if tool == "codex":
        return [
            "exec",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            prompt,
        ]
    if tool == "grok":
        return ["-p", prompt, "--no-wait-for-background"]
    if tool == "hermes":
        return ["chat", "-Q", "-q", prompt]
    if tool in ("mi", "pi"):
        return ["-p", prompt]
    if tool == "opencode":
        return ["run", prompt]
    raise ValueError(f"Unsupported demo tool '{tool}'.")


def launch_base(args: Args) -> list[str]:
    cmd = ["harbor", "launch", "--backend", args.backend]
    if args.model:
        cmd.extend(["--model", args.model])
    return cmd


def config_cmd(args: Args) -> list[str]:
    return [*launch_base(args), "--config", args.tool]


def direct_cmd(args: Args) -> list[str]:
    return [*launch_base(args), args.tool, *prompt_args(args.tool, args.task)]


def web_cmd(args: Args) -> list[str]:
    return [
        "harbor",
        "launch",
        "--web",
        "--backend",
        args.backend,
        *([] if not args.model else ["--model", args.model]),
        args.tool,
        *prompt_args(args.tool, args.web_task),
    ]


def build_steps(args: Args) -> list[DemoStep]:
    return [
        DemoStep(
            "Preflight",
            [],
            "harbor launch is a route builder for host coding tools.",
            "The viewer needs the promise before any command output appears.",
            "Backend, model, host tool, and whether commands can run.",
            "What this demo does: Config -> Direct -> Web route.",
        ),
        DemoStep(
            "Status",
            [["harbor", "ps"]],
            "Harbor has service state before launch changes anything.",
            "A baseline makes the later --web service changes legible.",
            "Whether the backend, Boost, or SearXNG are already running.",
            "Show the current Harbor services before the launch route changes anything.",
        ),
        DemoStep(
            "Config",
            [config_cmd(args)],
            "harbor launch can prepare host-tool config without opening the tool.",
            "This removes manual provider URL, API key, and model wiring.",
            "Output naming the selected backend/model route or the written config.",
            "Generate or print the host-tool adapter configuration without starting the tool.",
        ),
        DemoStep(
            "Direct",
            [direct_cmd(args)],
            f"{tool_label(args.tool)} can use the local Harbor backend through that route.",
            "The feature is a working host-tool launch, not only config generation.",
            "A short tool response, or a clear readiness/error message.",
            f"Launch {tool_label(args.tool)} against the selected local backend.",
            skip_when_tool_missing=True,
        ),
        DemoStep(
            "Web route",
            [["harbor", "ps"], web_cmd(args), ["harbor", "ps"]],
            "The same route can be upgraded with Boost web tooling.",
            "--web is the visible capability jump without hand-wiring a new provider.",
            "The before/after service list and the web-enabled launch command.",
            "Show services before --web, run the web-enabled launch, then show services again.",
            skip_command_indexes_when_tool_missing=(1,),
        ),
        DemoStep(
            "Recap",
            [],
            "The reusable pattern is config, direct launch, optional web route.",
            "A great demo should leave the viewer with commands they can reuse.",
            "The three command shapes: --config, direct launch, and --web.",
            "The reusable path is config generation, direct host-tool launch, then optional --web routing.",
        ),
    ]


def validate_tool(tool: str) -> None:
    if tool == "claude":
        raise SystemExit(
            "Claude Code does not support --web in harbor launch. "
            f"Choose one of: {', '.join(SUPPORTED_TOOLS)}"
        )
    if tool not in SUPPORTED_TOOLS:
        raise SystemExit(
            f"Unsupported demo tool '{tool}'. Choose one of: {', '.join(SUPPORTED_TOOLS)}"
        )


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a non-negative integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def parse_args(argv: list[str]) -> Args:
    parser = argparse.ArgumentParser(
        description="Run a capture-friendly narrated demo for harbor launch.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  uv run scripts/demos/launch-tui.py --yes
  uv run scripts/demos/launch-tui.py --dry-run
  uv run scripts/demos/launch-tui.py --tui --yes
  scripts/demos/launch-tui.py --dry-run
  scripts/demos/launch-tui.py --backend ollama --model qwen3.5:4b --tool mi
  scripts/demos/launch-tui.py --allow-missing-tool --yes
  scripts/demos/launch-tui.py --record demo.cast --capture-mode asciinema --yes

Autoinstall:
  uv run scripts/demos/launch-tui.py --yes

Modes:
  Default mode is a narrated terminal story.
  --tui opens the full-screen Textual dashboard.

Recording:
  --capture-mode asciinema wraps the live TUI with asciinema rec.
""",
    )
    parser.add_argument("--backend", default=os.environ.get("HARBOR_DEMO_BACKEND", DEFAULT_BACKEND))
    parser.add_argument("--model", default=os.environ.get("HARBOR_DEMO_MODEL", ""))
    parser.add_argument("--tool", default=os.environ.get("HARBOR_DEMO_TOOL", DEFAULT_TOOL))
    parser.add_argument("--task", default=os.environ.get("HARBOR_DEMO_TASK", DEFAULT_TASK))
    parser.add_argument("--web-task", default=os.environ.get("HARBOR_DEMO_WEB_TASK", DEFAULT_WEB_TASK))
    parser.add_argument("--allow-missing-tool", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--record", default="")
    parser.add_argument(
        "--capture-mode",
        choices=("none", "asciinema", "vhs"),
        default="none",
        help="Recording wrapper to use with --record. VHS prints a tape stub.",
    )
    parser.add_argument("--duration", type=positive_int, default=0, help="Exit live mode after this many seconds.")
    parser.add_argument("--yes", action="store_true", help="Skip the live-mode confirmation prompt.")
    parser.add_argument("--tui", action="store_true", help="Use the full-screen Textual dashboard.")
    ns = parser.parse_args(argv)
    validate_tool(ns.tool)
    return Args(
        backend=ns.backend,
        model=ns.model,
        tool=ns.tool,
        task=ns.task,
        web_task=ns.web_task,
        allow_missing_tool=ns.allow_missing_tool,
        dry_run=ns.dry_run,
        record=ns.record,
        capture_mode=ns.capture_mode,
        duration=ns.duration,
        yes=ns.yes,
        tui=ns.tui,
    )


def print_dry_run(args: Args) -> None:
    print()
    print("Harbor Launch Demo")
    print()
    print("Harbor launch is a route builder: it connects a host coding tool")
    print("to a local Harbor backend, then can add Boost web tooling to the")
    print("same route with --web.")
    print()
    print(f"Backend:      {args.backend}")
    print(f"Model:        {args.model or 'auto-discover'}")
    print(f"Tool:         {args.tool} ({tool_label(args.tool)})")
    print(f"Direct task:  {args.task}")
    print(f"Web task:     {args.web_task}")
    print()

    steps = build_steps(args)
    for index, step in enumerate(steps, start=1):
        print(f"Step {index}: {step.title}")
        print(f"  What this proves: {step.proves}")
        print(f"  Why it matters:   {step.why}")
        print(f"  What to look for: {step.look_for}")
        if not step.commands:
            if step.title == "Recap":
                print("  reuse: harbor launch --config -> harbor launch <tool> -> harbor launch --web")
            elif step.title == "Preflight":
                print("  intro screen; no command")
            else:
                print("  no command")
            continue
        if step.title == "Web route":
            labels = ("before", "launch", "after")
            for label, cmd in zip(labels, step.commands):
                print(f"  {label}: {display_command(cmd)}")
            continue
        for cmd in step.commands:
            print(f"  {display_command(cmd)}")
    print()


def print_vhs_tape(args: Args) -> None:
    inner = [
        sys.executable,
        os.path.abspath(__file__),
        "--backend",
        args.backend,
        "--tool",
        args.tool,
        "--yes",
    ]
    if args.model:
        inner.extend(["--model", args.model])
    if args.allow_missing_tool:
        inner.append("--allow-missing-tool")
    print('Output "harbor-launch.gif"')
    print("Set Shell bash")
    print("Set FontSize 18")
    print("Set Width 1280")
    print("Set Height 720")
    print(f"Type {shlex.quote(quote_cmd(inner))}")
    print("Enter")


def start_recording(args: Args, argv: list[str]) -> int:
    mode = args.capture_mode
    if mode == "none":
        mode = "asciinema"

    if mode == "vhs":
        print_vhs_tape(args)
        return 0

    if not shutil.which("asciinema"):
        print("ERROR: asciinema is required for --record with --capture-mode asciinema.", file=sys.stderr)
        return 1

    inner_args: list[str] = []
    skip_next = False
    for arg in argv:
        if skip_next:
            skip_next = False
            continue
        if arg == "--record":
            skip_next = True
            continue
        if arg.startswith("--record="):
            continue
        inner_args.append(arg)
    if "--yes" not in inner_args:
        inner_args.append("--yes")
    cmd = [sys.executable, os.path.abspath(__file__), *inner_args]
    return subprocess.call(["asciinema", "rec", args.record, "-c", quote_cmd(cmd)])


def import_textual() -> dict[str, object]:
    try:
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical
        from textual.widgets import Footer, Header, RichLog, Static
    except ImportError as exc:
        raise RuntimeError(
            "Textual is required for live mode. Install it with: python3 -m pip install textual"
        ) from exc

    return {
        "App": App,
        "ComposeResult": ComposeResult,
        "Horizontal": Horizontal,
        "Vertical": Vertical,
        "Footer": Footer,
        "Header": Header,
        "RichLog": RichLog,
        "Static": Static,
    }


def story_divider(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def print_step_brief(index: int, step: DemoStep) -> None:
    story_divider(f"Step {index}: {step.title}")
    print(f"What this proves: {step.proves}")
    print(f"Why it matters:   {step.why}")
    print(f"What to look for: {step.look_for}")
    print()


def run_streamed_command(command: list[str], harbor_bin: str) -> int:
    print(f"$ {display_command(command)}")
    run_command = execution_command(command, harbor_bin)
    if run_command != command:
        print(f"(executing with repo-local fallback: {display_command(run_command)})")
    proc = subprocess.Popen(
        run_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="")
    return proc.wait()


def run_story(args: Args) -> int:
    steps = build_steps(args)
    harbor_bin = resolve_harbor_bin()
    tool_missing = shutil.which(args.tool) is None

    print()
    print("Harbor Launch Demo")
    print()
    print("harbor launch is a route builder.")
    print("It connects a host coding tool to a local Harbor backend, then can")
    print("add Boost web tooling to that same route with --web.")
    print()
    print("This demo is intentionally sequential: one claim, one command, one thing to notice.")
    print()
    print(f"Backend: {args.backend}")
    print(f"Model:   {args.model or 'auto-discover'}")
    print(f"Tool:    {args.tool} ({tool_label(args.tool)})")
    if harbor_bin == "./harbor.sh":
        print("Harbor:  using ./harbor.sh for execution; displayed commands stay canonical.")
    else:
        print("Harbor:  harbor on PATH")
    print()

    if tool_missing and not args.allow_missing_tool:
        print(f"Host tool '{args.tool}' is not installed.")
        print("Install it or rerun with --allow-missing-tool to keep the story moving.")
        return 1

    if not args.yes and sys.stdin.isatty():
        print("This will run real Harbor commands.")
        print("Run with --dry-run if you only want the command plan.")
        input("Press Enter to start the narrated demo...")

    for index, step in enumerate(steps, start=1):
        print_step_brief(index, step)

        if step.title == "Preflight":
            print("Selected route:")
            print(f"  backend: {args.backend}")
            print(f"  model:   {args.model or 'auto-discover'}")
            print(f"  tool:    {args.tool} ({tool_label(args.tool)})")
            print(f"  harbor:  {harbor_bin}")
            print(f"  tool on PATH: {'yes' if not tool_missing else 'no'}")
            continue

        if step.title == "Recap":
            print("Reusable command shapes:")
            print("  harbor launch --config <tool>")
            print("  harbor launch --backend <backend> [--model <model>] <tool> ...")
            print("  harbor launch --web --backend <backend> [--model <model>] <tool> ...")
            continue

        if tool_missing and step.skip_when_tool_missing and args.allow_missing_tool:
            for command in step.commands:
                print(f"SKIP: host tool is missing; would run: {display_command(command)}")
            continue

        for command_index, command in enumerate(step.commands):
            if (
                tool_missing
                and args.allow_missing_tool
                and command_index in step.skip_command_indexes_when_tool_missing
            ):
                print(f"SKIP: host tool is missing; would run: {display_command(command)}")
                continue

            status = run_streamed_command(command, harbor_bin)
            print(f"\nexit {status}")
            if status != 0:
                print("Stopping here so the failing command remains visible.")
                return status

    print()
    print("Demo complete.")
    return 0


def make_app_class(textual: dict[str, object]) -> type:
    App = textual["App"]
    ComposeResult = textual["ComposeResult"]
    Horizontal = textual["Horizontal"]
    Vertical = textual["Vertical"]
    Footer = textual["Footer"]
    Header = textual["Header"]
    RichLog = textual["RichLog"]
    Static = textual["Static"]

    class StepList(Static):  # type: ignore[misc, valid-type]
        def update_steps(self, steps: list[DemoStep]) -> None:
            lines = ["Steps", ""]
            for index, step in enumerate(steps, start=1):
                lines.append(f"{index}. {step.status:<7} {step.title}")
            self.update("\n".join(lines))

    class HarborLaunchDemoApp(App):  # type: ignore[misc, valid-type]
        TITLE = "Harbor Launch Demo"
        SUB_TITLE = "host tool route for local backends"

        CSS = """
        Screen {
            background: #101418;
            color: #d8dee9;
        }
        #top-route {
            height: 3;
            padding: 0 1;
            background: #1f2933;
            color: #f8fafc;
        }
        #body {
            height: 1fr;
        }
        #steps {
            width: 30;
            padding: 1;
            background: #151b22;
            border: solid #334155;
        }
        #main {
            width: 1fr;
        }
        #command-panel {
            height: 4;
            padding: 1;
            background: #111827;
            border: solid #334155;
        }
        #output-log {
            height: 1fr;
            border: solid #334155;
        }
        #explain-panel {
            height: 6;
            padding: 1;
            background: #111827;
            border: solid #334155;
        }
        """

        BINDINGS = [("q", "quit", "Quit")]

        def __init__(self, args: Args) -> None:
            super().__init__()
            self.args = args
            self.steps = build_steps(args)
            self.started_at = time.monotonic()
            self.tool_missing = shutil.which(args.tool) is None
            self.harbor_bin = resolve_harbor_bin()

        def compose(self) -> ComposeResult:  # type: ignore[override]
            yield Header()
            yield Static("", id="top-route")
            with Horizontal(id="body"):
                yield StepList("", id="steps")
                with Vertical(id="main"):
                    yield Static("", id="command-panel")
                    yield RichLog(id="output-log", wrap=True, highlight=False)
                    yield Static("", id="explain-panel")
            yield Footer()

        def on_mount(self) -> None:
            self.refresh_route()
            self.refresh_steps()
            self.set_interval(1.0, self.refresh_route)
            if self.args.duration > 0:
                self.set_timer(float(self.args.duration), self.exit)
            asyncio.create_task(self.drive_demo())

        def refresh_route(self) -> None:
            elapsed = int(time.monotonic() - self.started_at)
            route = (
                f"Backend: {self.args.backend} | "
                f"Model: {self.args.model or 'auto-discover'} | "
                f"Tool: {self.args.tool} ({tool_label(self.args.tool)}) | "
                f"Elapsed: {elapsed}s"
            )
            self.query_one("#top-route", Static).update(route)

        def refresh_steps(self) -> None:
            self.query_one("#steps", StepList).update_steps(self.steps)

        def output_log(self):
            return self.query_one("#output-log", RichLog)

        def write_output(self, line: str = "") -> None:
            self.output_log().write(line)

        def show_step(self, step: DemoStep) -> None:
            if step.commands:
                command = "\n".join(f"$ {display_command(command)}" for command in step.commands)
            elif step.title == "Preflight":
                command = (
                    "What this demo does\n"
                    "Config -> Direct -> Web route\n"
                    "This demo runs real Harbor commands."
                )
            else:
                command = "No command. Review the route above."
            self.query_one("#command-panel", Static).update(f"{step.title}\n{command}")
            self.query_one("#explain-panel", Static).update(step.explanation)

        async def run_command(self, command: list[str]) -> int:
            self.write_output(f"$ {display_command(command)}")
            run_command = execution_command(command, self.harbor_bin)
            if run_command != command:
                self.write_output(f"(executing with repo-local fallback: {display_command(run_command)})")
            proc = await asyncio.create_subprocess_exec(
                *run_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                self.write_output(line.decode(errors="replace").rstrip())
            return await proc.wait()

        async def drive_demo(self) -> None:
            self.output_log().clear()
            if self.tool_missing and self.args.allow_missing_tool:
                self.write_output(
                    f"Host tool '{self.args.tool}' is not installed. "
                    "Direct and web launch steps will be shown as skipped."
                )
                self.write_output()

            for step in self.steps:
                self.show_step(step)
                if step.title == "Preflight":
                    step.status = "PASS"
                    self.write_output("What this demo does")
                    self.write_output()
                    self.write_output("This demo runs real Harbor commands to prove the launch route:")
                    self.write_output("1. Config: generate the host-tool adapter settings.")
                    self.write_output("2. Direct: run the selected host tool against the local backend.")
                    self.write_output("3. Web route: show services, run --web, then show services again.")
                    self.write_output()
                    self.write_output("Selected route:")
                    self.write_output(f"Backend: {self.args.backend}")
                    self.write_output(f"Model: {self.args.model or 'auto-discover'}")
                    self.write_output(f"Tool: {self.args.tool} ({tool_label(self.args.tool)})")
                    self.write_output(f"harbor on PATH: {'yes' if shutil.which('harbor') else 'no'}")
                    self.write_output(f"harbor executable: {self.harbor_bin}")
                    self.write_output(f"tool on PATH: {'yes' if not self.tool_missing else 'no'}")
                    self.write_output()
                    self.write_output("Use --dry-run first if you only want the command plan.")
                    self.write_output()
                    self.refresh_steps()
                    await asyncio.sleep(3.0)
                    continue

                if step.title == "Recap":
                    step.status = "PASS"
                    self.write_output()
                    self.write_output("Recap:")
                    self.write_output("1. --config writes the host-tool adapter route.")
                    self.write_output("2. Direct launch starts the host tool against the local backend.")
                    self.write_output("3. --web adds Boost and SearXNG to the route.")
                    self.refresh_steps()
                    continue

                if self.tool_missing and step.skip_when_tool_missing and self.args.allow_missing_tool:
                    step.status = "SKIP"
                    for command in step.commands:
                        self.write_output(f"SKIP: would run {display_command(command)}")
                    self.refresh_steps()
                    await asyncio.sleep(1.0)
                    continue

                step.status = "RUNNING"
                self.refresh_steps()
                skipped = False
                for command_index, command in enumerate(step.commands):
                    if (
                        self.tool_missing
                        and self.args.allow_missing_tool
                        and command_index in step.skip_command_indexes_when_tool_missing
                    ):
                        skipped = True
                        self.write_output(f"SKIP: would run {display_command(command)}")
                        self.write_output()
                        continue

                    try:
                        status = await self.run_command(command)
                    except FileNotFoundError as exc:
                        step.status = "FAIL"
                        self.write_output(f"ERROR: {exc.filename} is not installed or not on PATH.")
                        self.refresh_steps()
                        return

                    if status != 0:
                        step.status = "FAIL"
                        self.write_output(f"exit {status}")
                        self.write_output()
                        self.refresh_steps()
                        return
                    self.write_output(f"exit {status}")
                    self.write_output()

                step.status = "SKIP" if skipped else "PASS"
                self.refresh_steps()
                await asyncio.sleep(1.0)

            if self.args.duration == 0:
                self.write_output()
                self.write_output("Demo complete. Press q to quit.")

    return HarborLaunchDemoApp


def run_live(args: Args) -> int:
    if shutil.which(args.tool) is None and not args.allow_missing_tool:
        print(
            f"ERROR: Host tool '{args.tool}' is not installed. "
            "Install it or rerun with --allow-missing-tool.",
            file=sys.stderr,
        )
        return 1

    if not args.yes and sys.stdin.isatty():
        print("This demo runs real Harbor commands.")
        print("Route: Config -> Direct -> Web route")
        print("Run --dry-run first if you only want the command plan.")
        print()
        print(f"Backend: {args.backend}")
        print(f"Model:   {args.model or 'auto-discover'}")
        print(f"Tool:    {args.tool} ({tool_label(args.tool)})")
        input("Press Enter to start the TUI demo...")

    try:
        textual = import_textual()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    app_class = make_app_class(textual)
    app = app_class(args)
    app.run()
    return 0


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    if args.dry_run:
        print_dry_run(args)
        return 0

    if args.record:
        return start_recording(args, argv)

    if args.tui:
        return run_live(args)

    return run_story(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
