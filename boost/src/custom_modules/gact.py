from pydantic import BaseModel, Field
from typing import Optional, Union, Literal, Dict, List
from enum import Enum

import chat as ch
import llm
import custom_modules.recpl as recpl


class MouseButton(str, Enum):
  """Mouse button identifiers for click and drag operations"""
  LEFT = "left"
  RIGHT = "right"
  MIDDLE = "middle"


class BaseCommand(BaseModel):
  delay: Optional[float] = Field(
    default=0.0,
    description="Time to wait before executing this command, in seconds"
  )
  repeat: Optional[int] = Field(
    default=1, description="Number of times to repeat this command"
  )
  condition: Optional[dict] = Field(
    default=None,
    description="Conditional logic that must be met before executing command"
  )


class ClickCommand(BaseCommand):
  type: Literal["click"] = Field(
    description="Perform mouse click at specified coordinates"
  )
  params: dict[str, Union[int, MouseButton, float]] = Field(
    default={
      "x": 0,    # X coordinate on screen
      "y": 0,    # Y coordinate on screen
      "clicks": 1,    # Number of clicks to perform
      "interval": 0.0,    # Time between clicks in seconds
      "button": MouseButton.LEFT,    # Which mouse button to click
      "duration": 0.0    # How long to hold the click in seconds
    },
    description="Click parameters including position, count, timing, and button"
  )


class MoveCommand(BaseCommand):
  type: Literal["move"] = Field(
    description="Move mouse cursor to specified coordinates"
  )
  params: dict[str, Union[int, float]] = Field(
    default={
      "x": 0,    # Target X coordinate
      "y": 0,    # Target Y coordinate
      "duration": 0.0    # Time to take for movement
    },
    description=
    "Mouse movement parameters including target position and movement duration"
  )


class TypeCommand(BaseCommand):
  type: Literal["type"] = Field(description="Type text using keyboard")
  params: dict[str, Union[str, float]] = Field(
    default={
      "text": "",    # Text to type
      "interval": 0.0    # Time between keystrokes
    },
    description="Typing parameters including text content and keystroke timing"
  )


class LocateCommand(BaseCommand):
  type: Literal["locate"] = Field(description="Find image on screen")
  params: dict[str, Union[str, float]] = Field(
    default={
      "image": "",    # Path or reference to image to find
      "confidence": 0.9    # Match confidence threshold
    },
    description=
    "Image location parameters including target image and confidence level"
  )


class DragCommand(BaseCommand):
  type: Literal["drag"] = Field(
    description="Click and drag from current position to target coordinates"
  )
  params: dict[str, Union[int, float]] = Field(
    default={
      "x": 0,    # Target X coordinate
      "y": 0,    # Target Y coordinate
      "duration": 0.0,    # Time to take for drag
      "button":
        MouseButton.LEFT    # Which button to use for dragging
    },
    description=
    "Drag parameters including target position, duration, and mouse button"
  )


class ScrollCommand(BaseCommand):
  type: Literal["scroll"] = Field(description="Scroll mouse wheel")
  params: dict[str, Union[int, float]] = Field(
    default={
      "clicks": 0,    # Number of scroll increments (positive=up, negative=down)
      "x": None,    # X coordinate for scroll (optional)
      "y": None    # Y coordinate for scroll (optional)
    },
    description=
    "Scroll parameters including direction, amount, and optional position"
  )


class HotkeyCommand(BaseCommand):
  type: Literal["hotkey"] = Field(
    description="Press combination of keys simultaneously"
  )
  params: dict[str, List[str]] = Field(
    default={"keys": []},    # List of key names to press
    description="Hotkey parameters specifying key combination to press"
  )


class WaitCommand(BaseCommand):
  type: Literal["wait"] = Field(
    description="Pause execution for specified duration"
  )
  params: dict[str, float] = Field(
    default={"seconds": 1.0}, description="Wait duration in seconds"
  )


Command = Union[ClickCommand, MoveCommand, TypeCommand, LocateCommand,
                DragCommand, ScrollCommand, HotkeyCommand, WaitCommand]


class Script(BaseModel):
  name: str = Field(description="3-5 words outlining the purpose of the script")
  commands: List[Command] = Field(description="List of commands to execute")


ID_PREFIX = 'gact'

gact_prompt = """
<instruction>
Take a free-form desktop action plan and convert it into a structured JSON ready for automation.
</instruction>

<input name="Free-form action plan">
{script}
</input>

<output_format>
You will reply with a JSON object following this schema to the letter:
{response_schema}
</output_format>
""".strip()


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  recpl_chat = await recpl.call(chat, llm)
  recpl_chat.user(
    """
Resulting plan should be linear and atomic, with no conditional or optional steps.
Please reply with the revised plan only and nothing else.
    """
  )
  await recpl_chat.emit_advance()
  await chat.emit_status('Rewriting as a structured JSON...')

  await llm.stream_final_completion(
    prompt=gact_prompt,
    schema=Script,
    script=recpl_chat.tail.content,
    response_schema=Script.schema_json(indent=2),
    resolve=True
  )
