import random

import chat as ch
import llm
import log

ID_PREFIX = 'pad'

THINKING = [
  'Actively thinking...',
  'Considering possible implications...',
  'Simplifying...',
  'Ensuring correctness...',
  'Clarifying...',
  'Rephrasing a thought...',
  'Reconsidering...',
  'Evaluating assumption...',
  'Analyzing constraints...',
  'Reflecting on a solution...',
  'Reviewing...',
  'Contemplating...',
  'Pondering...',
  'Speculating...',
  'Deliberating...',
  'Focusing on the outcome...',
  'Imagining alternatives...',
  'Envisioning a simpler path...',
  'Creating a more concise outline...',
  'Constructing a more elaborate plan...',
  'Designing a more efficient solution...',
  'Inventing a more effective strategy...',
  'Devising a more practical approach...',
  'Formulating a more sophisticated method...',
  'Developing a more advanced technique...',
]

THINKING_2 = [
  'Thinking about task at hand',
  'Applying critical thinking',
  'Choosing more practical options',
  'Ensuring pragmatic solutions',
  'Simplifying',
  'Ensuring correctness',
  'Ensuring practicality'
  'Removing sources of ambiguity',
  'Making sure it makes sense',
  'Ensuring clarity',
  'Ensuring simplicity',
  'Making sure it\'s easy to understand',
  'Verifying the logic',
  'Checking for errors',
  'Making sure I did not miss anything',
  'Avoiding obvious mistakes',
  'Fixing an error',
  'Correcting a mistake',
  'Breaking down the problem',
  'Ensuring the solution is feasible',
  'Clarifying assumptions',
]

WORDS = [
  'apple', 'banana', 'cherry', 'date', 'elderberry', 'fig', 'grape', 'honeydew',
  'kiwi', 'lemon', 'mango', 'nectarine', 'orange', 'pear', 'quince',
  'raspberry', 'strawberry', 'tangerine', 'ugli', 'vanilla', 'watermelon',
  'ximenia', 'yuzu', 'zucchini'
]


def get_size(**kwargs):
  return int(kwargs.get('pad_size', 256))


def pad_thinking(**kwargs):
  size = get_size(**kwargs)
  join = kwargs.get('join', '\n')
  return join.join([random.choice(THINKING_2) for _ in range(size)])


def pad_newline(**kwargs):
  size = get_size(**kwargs)
  return '\n' * size


def pad_space(**kwargs):
  size = get_size(**kwargs)
  return ' ' * size


def pad_random_nl(**kwargs):
  size = get_size(**kwargs)
  return ''.join([random.choice([' ', '\n']) for _ in range(size)])


def random_alphabet():
  return random.choice('abcdefghijklmnopqrstuvwxyz')


def pad_random_alphabet(**kwargs):
  size = get_size(**kwargs)
  join = kwargs.get('join', '')
  pad = join.join([random_alphabet() for _ in range(size)])
  return pad


def pad_random_words(**kwargs):
  size = get_size(**kwargs)
  pad = ' '.join([random.choice(WORDS) for _ in range(size)])
  return pad


def pad_random_numbers(**kwargs):
  size = get_size(**kwargs)
  pad = ' '.join([str(random.randint(0, 9)) for _ in range(size)])
  return pad


def pad_thinking_loop(**kwargs):
  size = get_size(**kwargs)
  join = kwargs.get('join', '\n')
  return join.join([THINKING_2[i % len(THINKING_2)] for i in range(size)])

def pad_thinking_steps(**kwargs):
  size = get_size(**kwargs)
  join = kwargs.get('join', '\n')

  return join.join([f'Step {i}: {THINKING_2[i % len(THINKING_2)]}...' for i in range(size)])

def pad_random_thinking_steps(**kwargs):
  size = get_size(**kwargs)
  join = kwargs.get('join', '\n')

  return join.join([f'Step {i}: {random.choice(THINKING_2)}...' for i in range(size)])


PAD_TYPES = {
  'thinking': pad_thinking,
  'newline': pad_newline,
  'space': pad_space,
  'random_nl': pad_random_nl,
  'random_alphabet': pad_random_alphabet,
  'random_words': pad_random_words,
  'random_numbers': pad_random_numbers,
  'thinking_loop': pad_thinking_loop,
  'thinking_steps': pad_thinking_steps,
  'random_thinking_steps': pad_random_thinking_steps,
}

PAD_STYLES = {
  'plain': lambda x: x,
  'block': lambda x: f"""
```entropy
{x}
```
""".strip(),
  'block_thoughts': lambda x: f"""
```thoughts
Starting internal thought process...
{x}
Ok, I am ready for the final answer now.
```
""".strip(),
  'quote': lambda x: f"""
> {x}
""".strip(),
}


def make_pad(**kwargs):
  pad_type = kwargs.get('pad_type', 'random_thinking_steps')
  pad_style = kwargs.get('pad_style', 'block_thoughts')

  return PAD_STYLES[pad_style](PAD_TYPES[pad_type](**kwargs))


logger = log.setup_logger(__name__)


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  llm.boost_params['pad_size'] = '128'

  pad = make_pad(**llm.boost_params)

  chat.user(
    f"""
Before addresing my request, I need you to take your time and think for a while.
It's very important for you to utilise this time to concentrate on the task at hand.
""".strip()
  )

  await chat.emit_status('Thinking...')

  chat.assistant(
    f"""
Thank you for letting me think for a bit! I will use this time to concentrate on the task at hand.
{pad}
  """.strip()
  )
  await llm.emit_message(chat.tail.content)

  chat.user(
    f"""
Ok, I think we're ready now. Please answer my previous request.
  """.strip()
  )

  await chat.emit_status('Final')
  await llm.stream_final_completion()
