from chat import Chat

DIRECT_TASK_PROMPTS = [
    # Open WebUI prompts related to system tasks
  'Create a concise, 3-5 word title with an emoji as a title for the chat history',
  'Based on the chat history, determine whether a search is necessary',
  'Generate 1-3 broad tags categorizing the main themes of the chat history',
  'You are an autocompletion system. Continue the text in `<text>` based on the **completion type**',
  # Custom for the test
  '[{DIRECT}]'
]

def is_direct_task(chat: Chat):
  return any(chat.has_substring(prompt) for prompt in DIRECT_TASK_PROMPTS)
