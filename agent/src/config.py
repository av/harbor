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


# ----------------- LLM -----------------

HARBOR_AGENT_LLM_URL = Config[str](
  name='HARBOR_AGENT_LLM_URL',
  type=str,
  # Default is Harbor's own Ollama
  default='http://ollama:11434/v1',
  description='An OpenAI-compatible inference API with vision and structured outputs. By default will use Harbor\'s Ollama instance'
)

HARBOR_AGENT_LLM_PARAMS = Config[ConfigDict](
  name='HARBOR_AGENT_LLM_PARAMS',
  type=ConfigDict,
  # default='model=llama3.2-vision:11b-instruct-q8_0,temperature=0',
  default='model=minicpm-v:8b-2.6-q8_0,temperature=0',
  description='Subset of payload to be sent to the LLM chat completion API, including model, temperature, etc.'
)

HARBOR_AGENT_LLM_EXTRA_HEADERS = Config[ConfigDict](
  name='HARBOR_AGENT_LLM_EXTRA_HEADERS',
  type=ConfigDict,
  default='',
  description='Extra headers to be sent to the LLM chat completion API'
)

HARBOR_AGENT_LLM_EXTRA_QUERY_PARAMS = Config[ConfigDict](
  name='HARBOR_AGENT_LLM_EXTRA_QUERY_PARAMS',
  type=ConfigDict,
  default='',
  description='Extra query parameters to be sent to the LLM chat completion API'
)

# ----------------- API -----------------

HARBOR_AGENT_API_KEY = Config[str](
  name='HARBOR_AGENT_API_KEY',
  type=str,
  default='',
  description='The API key to use for the Agent API'
)

HARBOR_AGENT_API_KEYS = Config[StrList](
  name='HARBOR_AGENT_API_KEYS',
  type=StrList,
  default='',
  description='A colon-separated list of API keys to use for the Agent API'
)

HARBOR_AGENT_EXTRA_KEYS = Config[str](
  name='HARBOR_BOOST_API_KEY_*',
  type=str,
  default='',
  description='Named API keys to use for the Agent API'
)

# All possible API keys
AGENT_AUTH = [
  key for key in [HARBOR_AGENT_API_KEY.value, *HARBOR_AGENT_API_KEYS.value, *HARBOR_AGENT_EXTRA_KEYS.value] if key
]

# ----------------- Behavior -------------

INTERMEDIATE_OUTPUT = Config[bool](
  name='HARBOR_AGENT_INTERMEDIATE_OUTPUT',
  type=bool,
  default='true',
  description='Whether to expose intermediate completion results via the API'
)

STATUS_STYLE = Config[str](
  name='HARBOR_AGENT_STATUS_STYLE',
  type=str,
  default='md:codeblock',
  description='The style of status messages'
)

