#!/usr/bin/env python3
import json
from pathlib import Path
from typing import Annotated

import typer
from harbor.cli.main import app
from harbor.cli import jobs, notifications
from rich.console import Console


command_name = "harbor agenteval"


class CommandConsole(Console):
    def print(self, *objects, **kwargs):
        objects = tuple(
            item.replace("`harbor ", f"`{command_name} ")
            if isinstance(item, str) else item
            for item in objects
        )
        super().print(*objects, **kwargs)


# Keep upstream follow-up hints inside the visible wrapper command.
jobs.console = CommandConsole()
notifications.console = CommandConsole()
for command in app.registered_commands:
    if command.help:
        command.help = command.help.replace("`harbor ", f"`{command_name} ")


@app.command()
def results(job: Annotated[str, typer.Argument(help="Job name under the workspace jobs directory.")]):
    """Show the saved result of a local evaluation without a model call."""
    path = Path("jobs") / job / "result.json"
    try:
        result = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise typer.BadParameter(f"Cannot read {path}: {error}") from error
    stats = result["stats"]
    typer.echo(f"Job: {job}")
    typer.echo(f"Completed: {stats['n_completed_trials']}")
    typer.echo(f"Errors: {stats['n_errored_trials']}")
    for summary in stats["evals"].values():
        for metric in summary["metrics"]:
            if "mean" in metric:
                typer.echo(f"Mean reward: {metric['mean']}")
    typer.echo(f"Results: {path}")


if __name__ == "__main__":
    app(prog_name=command_name)
