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
