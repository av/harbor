from typing import Optional, Generic, TypeVar, List, Union, Type, Dict
import os

T = TypeVar('T')


class ConfigDict(Dict[str, Union[str, int, float, bool]]):

  @classmethod
  def from_string(cls, value: str) -> 'ConfigDict':
    result = cls()
    if not value:
      return result
    pairs = value.split(',')
    for pair in pairs:
      key, val = pair.split('=')
      key = key.strip()
      val = val.strip()
      # Try to parse the value as int, float, or bool
      if val.lower() == 'true':
        result[key] = True
      elif val.lower() == 'false':
        result[key] = False
      else:
        try:
          result[key] = int(val)
        except ValueError:
          try:
            result[key] = float(val)
          except ValueError:
            result[key] = val
    return result


class StrList(List[str]):

  @classmethod
  def from_string(cls, value: str) -> 'StrList':
    return cls(item.strip() for item in value.split(';') if item.strip()
              ) if value.strip() else cls()


class IntList(List[int]):

  @classmethod
  def from_string(cls, value: str) -> 'IntList':
    return cls(int(item.strip()) for item in value.split(';') if item.strip()
              ) if value.strip() else cls()


class FloatList(List[float]):

  @classmethod
  def from_string(cls, value: str) -> 'FloatList':
    return cls(
      float(item.strip()) for item in value.split(';') if item.strip()
    ) if value.strip() else cls()


class BoolList(List[bool]):

  @classmethod
  def from_string(cls, value: str) -> 'BoolList':
    return cls(
      item.strip().lower() == 'true'
      for item in value.split(';')
      if item.strip()
    ) if value.strip() else cls()


class Config(Generic[T]):
  name: str
  type: Type[T]
  default: str
  description: Optional[str]
  __value__: T

  def __init__(
    self,
    name: str,
    type: Type[T],
    default: str,
    description: Optional[str] = None
  ):
    self.name = name
    self.type = type
    self.default = default
    self.description = description
    self.__value__ = self.resolve_value()

  @property
  def value(self) -> T:
    return self.__value__

  def resolve_value(self) -> Union[T, List[T]]:
    if '*' in self.name:
      return self._resolve_wildcard()
    else:
      return self._resolve_single()

  def _resolve_single(self) -> T:
    raw_value = os.getenv(self.name, self.default)
    if isinstance(raw_value, list):
      raw_value = raw_value[0] if raw_value else ''
    return self._convert_value(raw_value)

  def _resolve_wildcard(self) -> List[T]:
    prefix = self.name.replace('*', '')
    matching_vars = [
      (key, value)
      for key, value in os.environ.items()
      if key.startswith(prefix)
    ]

    if not matching_vars:
      if isinstance(self.default, str):
        return [self._convert_value(self.default)] if self.default else []
      return self.default

    return [self._convert_value(value) for _, value in sorted(matching_vars)]

  def _convert_value(self, value: str) -> T:
    if issubclass(
      self.type, (StrList, IntList, FloatList, BoolList, ConfigDict)
    ):
      return self.type.from_string(value)
    elif self.type == str:
      return value
    elif self.type == int:
      return int(value)
    elif self.type == float:
      return float(value)
    elif self.type == bool:
      return value.lower() in ('true', '1', 'yes', 'on')
    else:
      return self.type(value)


# ----------------- APIs -----------------

HARBOR_OPENAI_URLS = Config[StrList](
  name='HARBOR_OPENAI_URLS',
  type=StrList,
  default='',
  description="""
An alias for `HARBOR_BOOST_OPENAI_URLS`.
""".strip()
)

HARBOR_OPENAI_KEYS = Config[StrList](
  name='HARBOR_OPENAI_KEYS',
  type=StrList,
  default='',
  description="""
An alias for `HARBOR_BOOST_OPENAI_KEYS`.
""".strip()
)

HARBOR_BOOST_OPENAI_URLS = Config[StrList](
  name='HARBOR_BOOST_OPENAI_URLS',
  type=StrList,
  default='',
  description="""
A semicolon-separated list of URLs to the OpenAI APIs to boost.
Prefer using named APIs via `HARBOR_BOOST_OPENAI_URL_*` and `HARBOR_BOOST_OPENAI_KEY_*` instead.
Must index-match contents of `HARBOR_BOOST_OPENAI_KEYS`.

Example:
```bash
HARBOR_OPENAI_URLS=https://localhost:11434/v1;https://localhost:8080/v1
```
""".strip()
)

HARBOR_BOOST_OPENAI_KEYS = Config[StrList](
  name='HARBOR_BOOST_OPENAI_KEYS',
  type=StrList,
  default='',
  description="""
A semicolon-separated list of API keys to use for the OpenAI APIs to boost.
Prefer using named APIs via `HARBOR_BOOST_OPENAI_URL_*` and `HARBOR_BOOST_OPENAI_KEY_*` instead.
Must index-match contents of `HARBOR_BOOST_OPENAI_URLS`.

Example:
```bash
HARBOR_OPENAI_KEYS=sk-abc123;sk-def456
```
""".strip()
)

HARBOR_BOOST_EXTRA_OPENAI_URLS = Config[str](
  name='HARBOR_BOOST_OPENAI_URL_*',
  type=str,
  default='',
  description="""
Named OpenAI-compatible API URLs to boost.
`*` means multiple variables can be defined with arbitrary postfix.

Example:
```bash
HARBOR_BOOST_OPENAI_URL_OLLAMA=https://localhost:11434/v1
HARBOR_BOOST_OPENAI_KEY_OLLAMA=sk-ollama123

HARBOR_BOOST_OPENAI_URL_HF=https://api-inference.huggingface.co/v1
HARBOR_BOOST_OPENAI_KEY_HF=sk-hf456
```
"""
)

HARBOR_BOOST_EXTRA_OPENAI_KEYS = Config[str](
  name='HARBOR_BOOST_OPENAI_KEY_*',
  type=str,
  default='',
  description="""
Example:
```bash
HARBOR_BOOST_OPENAI_URL_OLLAMA=https://localhost:11434/v1
HARBOR_BOOST_OPENAI_KEY_OLLAMA=sk-ollama123

HARBOR_BOOST_OPENAI_URL_HF=https://api-inference.huggingface.co/v1
HARBOR_BOOST_OPENAI_KEY_HF=sk-hf456
```
""".strip()
)

# Combining all the sources from
# above into a single list
BOOST_APIS = [
  *HARBOR_OPENAI_URLS.value, *HARBOR_BOOST_OPENAI_URLS.value,
  *HARBOR_BOOST_EXTRA_OPENAI_URLS.value
]

BOOST_KEYS = [
  *HARBOR_OPENAI_KEYS.value, *HARBOR_BOOST_OPENAI_KEYS.value,
  *HARBOR_BOOST_EXTRA_OPENAI_KEYS.value
]

EXTRA_LLM_PARAMS = Config[ConfigDict](
  name='HARBOR_BOOST_EXTRA_LLM_PARAMS',
  type=ConfigDict,
  default='temperature=0.35',
  description="""
Allows to specify extra payload for /chat/completions endpoints for all downstream services at once.
Format is `key=value,key2=value2,...`.

Example:
```bash
HARBOR_BOOST_EXTRA_LLM_PARAMS=temperature=0.35,top_p=0.9

# Be careful using provider-specific parameters
HARBOR_BOOST_EXTRA_LLM_PARAMS=temperature=0.12,max_ctx=8192
```
""".strip()
)

# ----------------- MODULES -----------------

BOOST_MODS = Config[StrList](
  name='HARBOR_BOOST_MODULES',
  type=StrList,
  default='all',
  description="""
A list of boost modules that will be advertised by `/v1/models` endpoint.
All loaded modules can still be used directly, this configuration only affects
which modules are advertised in the API.

Supports `all` value to enable all modules.

Example:
```bash
# Serve all modules
HARBOR_BOOST_MODULES=all

# Only serve klmbr and rcn modules
HARBOR_BOOST_MODULES=klmbr;rcn
```

When using with Harbor, you can configure this via Harbor CLI:

```bash
# Enable the module
harbor boost modules add <module>
# Disable the module
harbor boost modules rm <module>
# List enabled modules
harbor boost modules ls
```


Note that new Harbor releases might introduce new modules, so the default value of this setting could change in the future. Check out [Harbor Profiles](./3.-Harbor-CLI-Reference#harbor-profile) for a way to save and restore your configuration.

""".strip()
)

BOOST_FOLDERS = Config[StrList](
  name='HARBOR_BOOST_MODULE_FOLDERS',
  type=StrList,
  default='modules;custom_modules',
  description="""
A list of folders to load boost modules from.
You can mount custom modules to the `/boost/custom_modules` or a custom location and use this configuration to load them.

Example:
```bash
# Load from default locations
HARBOR_BOOST_MODULE_FOLDERS=modules;custom_modules

# Disable all built-in modules and load only custom ones
HARBOR_BOOST_MODULE_FOLDERS=/some/custom/path
```
""".strip()
)

# ---------------- COMPLETION ---------------

INTERMEDIATE_OUTPUT = Config[bool](
  name='HARBOR_BOOST_INTERMEDIATE_OUTPUT',
  type=bool,
  default='true',
  description="""
When set to `true`, the boost output the intermediate steps of the module, not only the final result, providing more dynamic feedback to the user.

Intermediate output includes status messages, internal monologue, and other non-final completions. Note that it doesn't mean "all output" from the module, as the module source can still decide to not emit specific things at all, or inverse - emit them even if this setting is off.

Example of the intermediate output from the `g1` module - underlying reasoning steps:

![example of intermediate output from g1 boost module](./g1-reasoning.png)
""".strip()
)

STATUS_STYLE = Config[str](
  name='HARBOR_BOOST_STATUS_STYLE',
  type=str,
  default='md:codeblock',
  description="""
A module can call `llm.emit_status` during its processing, which will be streamed as a "status" or "progress" message to the user. This setting controls the format of this message, which will be dependent on what's supported by the frontend where boost response is displayed.

Options:

````bash
md:codeblock "\n```boost\n{status}\n```\n",
md:h1        "\n\n# {status}\n\n",
md:h2        "\n\n## {status}\n\n",
md:h3        "\n\n### {status}\n\n",
plain        "\n\n{status}\n\n",
none         ""
````

The default is `md:codeblock` and looks like this in the WebUI:

![screenshot of status in the webui](./webui-boost-status.png)
""".strip()
)

# ---------------- BEHAVIOR -----------------

SERVE_BASE_MODELS = Config[bool](
  name='HARBOR_BOOST_BASE_MODELS',
  type=bool,
  default='false',
  description="""
Depending on the configuration of your setup, your LLM backend might or might not be connected to the UI directly. If not (or using boost as a standalone service), you can toggle this option on for the `boost` to serve them as is.

```bash
# Now "unboosted" models will also be available
# via the boost API
harbor config boost.base_models true
```
""".strip()
)

MODEL_FILTER = Config[ConfigDict](
  name='HARBOR_BOOST_MODEL_FILTER',
  type=ConfigDict,
  default='',
  description="""
When specified, `boost` will only serve models matching the filter. The filter is a key/value expression that'll be matched against the model metadata. See examples below:

```bash
# Only boost models with the "llama" in the name
harbor config set boost.model_filter id.contains=llama
# Only boost models matching the regex
harbor config set boost.model_filter id.regex=.+q8_0$
# Boost by regex matching multiple IDs
harbor config set boost.model_filter "id.regex=.*(llama3.1:8b|llama3.2:3b|qwen2.5:7b)"
# Only boost a model with the exact ID
harbor config set boost.model_filter id=llama3.1:8b
```

This filter runs _after_ the boosted models (per module) are added, so you can filter them out as well.
""".strip()
)

API_KEY = Config[str](
  name='HARBOR_BOOST_API_KEY',
  type=str,
  default='',
  description="""
By default, boost will accept and serve any request, but you can configure one or more API keys to restrict access to the service.

Example:

```bash
# Configure the API key
HARBOR_BOOST_API_KEY=sk-boost
# Send the API key in the header
# Authorization: sk-boost
```
""".strip()
)

API_KEYS = Config[StrList](
  name='HARBOR_BOOST_API_KEYS',
  type=StrList,
  default='',
  description="""
A colon-separated list of API keys to use for the boost API. Counterpart to `HARBOR_BOOST_API_KEY`.

Example:
```bash
# Configure the API keys
HARBOR_BOOST_API_KEYS=sk-user1;sk-user2;sk-user3
```

""".strip()
)

EXTRA_KEYS = Config[str](
  name='HARBOR_BOOST_API_KEY_*',
  type=str,
  default='',
  description="""
Allows specifying additional, "named" API keys that will be accepted by the boost API.

Example:
```bash
# Configure the API keys
HARBOR_BOOST_API_KEY_MAIN=sk-main

# Temporary API key for testing
HARBOR_BOOST_API_KEY_TEST=sk-test
```

""".strip()
)

BOOST_AUTH = [
  key for key in [API_KEY.value, *API_KEYS.value, *EXTRA_KEYS.value] if key
]

BOOST_PUBLIC_URL = Config[str](
  name='HARBOR_BOOST_PUBLIC_URL',
  type=str,
  default='http://localhost:34131',
  description='URL which boost artifacts should use to access the boost API'
)

# ------------------ KLMBR ------------------

KLMBR_PERCENTAGE = Config[int](
  name='HARBOR_BOOST_KLMBR_PERCENTAGE',
  type=int,
  default='15',
  description='The percentage of text to modify with the klmbr module'
)

KLMBR_MODS = Config[StrList](
  name='HARBOR_BOOST_KLMBR_MODS',
  type=StrList,
  default='all',
  description=f'The list of modifications klmbr will apply'
)

KLMBR_STRAT = Config[str](
  name='HARBOR_BOOST_KLMBR_STRAT',
  type=str,
  default='all',
  description='The strategy that selects messages to modify for the klmbr module'
)

KLMBR_STRAT_PARAMS = Config[ConfigDict](
  name='HARBOR_BOOST_KLMBR_STRAT_PARAMS',
  type=ConfigDict,
  default='',
  description=
  'The parameters for the strategy that selects messages to modify for the klmbr module'
)

# ----------------- RCN -----------------

RCN_STRAT = Config[str](
  name='HARBOR_BOOST_RCN_STRAT',
  type=str,
  default='match',
  description='The strategy that selects messages to modify for the rcn module'
)

RCN_STRAT_PARAMS = Config[ConfigDict](
  name='HARBOR_BOOST_RCN_STRAT_PARAMS',
  type=ConfigDict,
    # Default - last user message
  default='role=user,index=-1',
  description='Parameters for rcn message selection'
)

# ----------------- G1 -----------------

G1_STRAT = Config[str](
  name='HARBOR_BOOST_G1_STRAT',
  type=str,
  default='match',
  description='The strategy that selects messages to modify for the g1 module'
)

G1_STRAT_PARAMS = Config[ConfigDict](
  name='HARBOR_BOOST_G1_STRAT_PARAMS',
  type=ConfigDict,
    # Default - last user message
  default='role=user,index=-1',
  description='Parameters for g1 message selection'
)

G1_MAX_STEPS = Config[int](
  name='HARBOR_BOOST_G1_MAX_STEPS',
  type=int,
  default='15',
  description='The maximum number of reasoning steps to generate'
)

# ----------------- MCTS -----------------

MCTS_STRAT = Config[str](
  name='HARBOR_BOOST_MCTS_STRAT',
  type=str,
  default='match',
  description='The strategy that selects messages to target for the mcts module'
)

MCTS_STRAT_PARAMS = Config[ConfigDict](
  name='HARBOR_BOOST_MCTS_STRAT_PARAMS',
  type=ConfigDict,
    # Default - last user message
  default='role=user,index=-1',
  description='Parameters for mcts message selection'
)

MCTS_MAX_SIMULATIONS = Config[int](
  name='HARBOR_BOOST_MCTS_MAX_SIMULATIONS',
  type=int,
  default='2',
  description='The maximum number of simulations to run (per iteration)'
)

MCTS_MAX_ITERATIONS = Config[int](
  name='HARBOR_BOOST_MCTS_MAX_ITERATIONS',
  type=int,
  default='2',
  description='The maximum number of iterations to run'
)

MCTS_THOUGHTS = Config[int](
  name='HARBOR_BOOST_MCTS_THOUGHTS',
  type=int,
  default='2',
  description=
  'The amount of thoughts (node expansions) to generate per simulation'
)

MCTS_EXPLORATION_CONSTANT = Config[float](
  name='HARBOR_BOOST_MCTS_EXPLORATION_CONSTANT',
  type=float,
  default='1.414',
  description='The exploration constant for the MCTS algorithm'
)

# ----------------- ELI5 -----------------

ELI5_STRAT = Config[str](
  name='HARBOR_BOOST_ELI5_STRAT',
  type=str,
  default='match',
  description='The strategy that selects messages to target for the eli5 module'
)

ELI5_STRAT_PARAMS = Config[ConfigDict](
  name='HARBOR_BOOST_ELI5_STRAT_PARAMS',
  type=ConfigDict,
    # Default - last user message
  default='role=user,index=-1',
  description='Parameters for eli5 message selection'
)

# ----------- SUPERSUMMER ----------------

SUPERSUMMER_STRAT = Config[str](
  name='HARBOR_BOOST_SUPERSUMMER_STRAT',
  type=str,
  default='match',
  description=
  'The strategy that selects messages to target for the supersummer module'
)

SUPERSUMMER_STRAT_PARAMS = Config[ConfigDict](
  name='HARBOR_BOOST_SUPERSUMMER_STRAT_PARAMS',
  type=ConfigDict,
    # Default - last user message
  default='role=user,index=-1',
  description='Parameters for supersummer message selection'
)

SUPERSUMMER_NUM_QUESTIONS = Config[int](
  name='HARBOR_BOOST_SUPERSUMMER_NUM_QUESTIONS',
  type=int,
  default='5',
  description='The number of questions to generate for the summarisation'
)

SUPERSUMMER_LENGTH = Config[str](
  name='HARBOR_BOOST_SUPERSUMMER_LENGTH',
  type=str,
  default='few paragraphs',
  description='Desired length of the summary'
)

# ----------------- R0 -----------------

R0_THOUGHTS = Config[int](
  name='HARBOR_BOOST_R0_THOUGHTS',
  type=int,
  default='5',
  description='The amount of thoughts to generate for the r0 module'
)

if __name__ == '__main__':
  # Render documentation
  configs = [item for item in globals().values() if isinstance(item, Config)]

  docs = '''
# Harbor Boost Configuration

Harbor Boost is configured using environment variables. Following options are available:
  '''

  for config in configs:
    docs += f'\n\n## {config.name}\n'
    docs += f'> **Type**: `{config.type.__name__}`<br/>\n'
    docs += f'> **Default**: `{config.default}`<br/>\n'

    if config.description:
      docs += f'\n{config.description}\n'

  print(docs)
