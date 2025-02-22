import llm

class LLMRegistry:
  def __init__(self):
    self._registry = {}

  def register(self, instance: 'llm.LLM'):
    self._registry[instance.id] = instance

  def get(self, llm_id):
    return self._registry.get(llm_id)

  def unregister(self, instance: 'llm.LLM'):
    del self._registry[instance.id]

  def list_all(self):
    return list(self._registry.values())

llm_registry = LLMRegistry()