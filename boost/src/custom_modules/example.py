import llm
import log
import chat as ch

ID_PREFIX = 'example'
logger = log.setup_logger(ID_PREFIX)


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  """
  1. Working with a chat and chat nodes instances
  This is where you can create some content programmatically,
  that will later can be used for retrieving completions from
  the downstream model.
  """
  logger.debug(f"Example chat: {chat}")

  # Add new messages to the chat (no completions at this stage)
  chat.user("Hello!")
  chat.assistant("Hi! Would you like to learn more about Harbor Boost?")
  chat.add_message(
    role="harbor",
    content="Harbor Boost is an optimising LLM proxy with lots of cool features"
  )

  logger.debug(
    f"Chat history is a plain array of messages, from the tail: {chat.history()}"
  )
  logger.debug(
    f"Chat plain is a list of chat nodes, from the tail: {chat.plain()}"
  )

  # Tail is where the chat currently ends
  # In this instance, that's a message from "harbor"
  # role above
  tail = chat.tail

  logger.debug(
    f'Get all parents leading to a specific chat node: {tail.parents()}'
  )
  logger.debug(f'Get one immediate parent: {tail.parent}')

  # We can modify the chat from the tail node directly
  new_tail = tail.add_child(
    ch.ChatNode(role="harbor", content="Chat nodes are everywhere!")
  )

  # However, such modifications are not reflected in the parent
  # chat instance:
  logger.debug(chat.tail == tail)    # True
  logger.debug(chat.tail == new_tail)    # False

  # You can set a new tail for the chat, however
  chat.tail = new_tail
  # However, it's much easier to just work from the chat itself
  chat.user('Alright, I think that is mostly it for now. Thanks!')

  # You can create new chat instances as needed
  life_chat = ch.Chat.from_conversation(
    [
      {
        "role": "user",
        "content": "What is the meaning of life? Answer with a tongue twister."
      }
    ]
  )
  """
  3.1 Programmatic messages and statuses
  programmatic "public" messages that are streamed
  back to the client as they are emitted here
  (no way to "undo" or rewrite them)
  """
  # You can tweak how status messages are delivered
  # via the BOOST_STATUS_STYLE config option.
  await llm.emit_status('Status and message examples')
  await llm.emit_message("We can emit text at any time. ")
  await llm.emit_message(
    "\n_Note that you are responsible for correct formatting._\n"
  )
  """
  3.2. Internal LLM completions
  "llm" is a representation of the downstream model
  that is being boosted. It comes with a few helper
  methods that tie up the module workflow together and
  is pre-configured to hit the downstream API with expected parameters.

  The completions below are "internal", they are not streamed
  back to the client by default. Read further for "streamed" or
  "public" completions.
  """
  await llm.emit_status('Collecting internal completions...')
  word = "Roses"
  results = [
    # You can retrieve completion for some plain text
    await llm.chat_completion(prompt="Hi!", resolve=True),
    # You can include key/value pairs to be formatted in the prompt
    await llm.chat_completion(
      prompt="Tell me about {word} in ONE SHORT SENTENCE.",
      word=word,
      resolve=True,
    ),
    # You can also provide a list of messages
    # in the OpenAI-compatible format
    await llm.chat_completion(
      messages=[
        {
          "role": "user",
          "content": "Tell me about roses"
        }, {
          "role": "assistant",
          "content": "Sure, I can reply in three words! Here they are:"
        }
      ],
      resolve=True
    ),
    # You can also provide a chat instance,
    # Note that "resolve" is not set - the result
    # will be in raw API format
    f"\n```json\n{await llm.chat_completion(chat=life_chat)}\n```\n"
  ]
  # Results will now appear in the user's message
  await llm.emit_status('Displaying collected results')
  for i, result in enumerate(results):
    await llm.emit_message(f"\nResult {i}: {result}\n")
  """
  3.3. Public/Streamed LLM completions
  You can decide to stream responses from the downstream LLM
  as they are being generated, for example when there's a long
  chunk that needs to be retained in the global response.
  """
  await llm.emit_status('Response streaming examples')

  # Same signatures as chat_completion
  streamed_results = [
    # You can retrieve completion for some plain text
    await llm.stream_chat_completion(prompt="Hi!"),
    # You can include key/value pairs to be formatted in the prompt
    await llm.stream_chat_completion(
      prompt="Tell me about {word} in ONE SHORT SENTENCE.",
      word=word,
    ),
    # You can also provide a list of messages
    # in the OpenAI-compatible format
    await llm.stream_chat_completion(
      messages=[
        {
          "role": "user",
          "content": "Tell me about roses"
        }, {
          "role": "assistant",
          "content": "Sure, I can reply in three words! Here they are:"
        }
      ],
    ),
    # You can also provide a chat instance
    await llm.stream_chat_completion(chat=life_chat)
  ]
  # Streamed results are still buffered and available
  # for you to use (plain text).
  logger.debug(f"Streamed results: {streamed_results}")

  # Note that it's on you to apply formatting that will make
  # sense in the context of the global message stream.
  await llm.emit_message("\nThose are all results so far.\n")
  """
  4. Final completion
  Note that none of the above will actually reach the Client
  if the BOOST_INTERMEDIATE_OUTPUT is set to "false".
  The "final" completion below, however, will *always* be streamed back.
  It accepts all the same inputs as "chat_completion" and "stream_chat_completion" above.
  You don't have to call it, but the output will be completely empty if the
  "final" completion is not called and intermediate outputs are disabled.

  Think of this as a way to wrap up the module execution and
  present the user with the final result.
  """
  await llm.emit_status('Final completion')
  await llm.stream_final_completion(prompt="Wish me a good luck!",)
