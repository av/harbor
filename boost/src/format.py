import re
from config import STATUS_STYLE

status_formatters = {
  "md:codeblock": "\n```boost\n{status}\n```\n",
  "md:h1": "\n\n# {status}\n\n",
  "md:h2": "\n\n## {status}\n\n",
  "md:h3": "\n\n### {status}\n\n",
  "plain": "\n\n{status}\n\n",
  "none": ""
}


def format_status(status: str):
  desired_format = STATUS_STYLE.value

  if desired_format not in status_formatters:
    desired_format = "md:codeblock"

  return status_formatters[desired_format].format(status=status)


def format_artifact(artifact: str):
  return f"\n```html\n{artifact}\n```\n"


def remove_html_code_blocks(text_content):
  """
    Removes all HTML markdown code blocks (```html...```) from a string.

    Args:
        text_content (str): The string containing potential HTML code blocks.

    Returns:
        str: The string with HTML code blocks removed.
    """
  regex_pattern = r"```html\n(.*?)\n```"
  cleaned_text = re.sub(regex_pattern, "", text_content, flags=re.DOTALL)
  return cleaned_text
