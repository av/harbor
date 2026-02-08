import asyncio
from collections import defaultdict

import log

logger = log.setup_logger(__name__)


class AsyncEventEmitter:

  def __init__(self):
    self._listeners = defaultdict(list)
    self._listeners_once = defaultdict(list)
    self._lock = asyncio.Lock()

  async def on(self, event_name: str, listener: callable):
    async with self._lock:
      self._listeners[event_name].append(listener)
    logger.debug(f"ON: {listener.__name__} for '{event_name}'")

  async def once(self, event_name: str, listener: callable):
    if not asyncio.iscoroutinefunction(listener):
      raise TypeError("Listener must be async")
    async with self._lock:
      self._listeners_once[event_name].append(listener)
    logger.debug(f"ONCE: {listener.__name__} for '{event_name}'")

  async def off(self, event_name: str, listener: callable):
    async with self._lock:
      removed = False
      if listener in self._listeners[event_name]:
        self._listeners[event_name].remove(listener)
        removed = True
      elif listener in self._listeners_once[event_name]:
        self._listeners_once[event_name].remove(listener)
        removed = True

      if removed:
        logger.debug(f"OFF: {listener.__name__} from '{event_name}'")
      else:
        logger.warning(f"OFF_NOT_FOUND: {listener.__name__} for '{event_name}'")

  async def remove_all_listeners(self, event_name: str = None):
    async with self._lock:
      if event_name:
        if event_name in self._listeners:
          del self._listeners[event_name]
        if event_name in self._listeners_once:
          del self._listeners_once[event_name]
        logger.debug(f"REMOVED_ALL: Listeners for '{event_name}'")
      else:
        self._listeners.clear()
        self._listeners_once.clear()
        logger.debug("REMOVED_ALL: All listeners for all events")

  async def emit(self, event_name: str, *args, **kwargs):
    listeners_to_call = []
    once_listeners_to_call = []

    async with self._lock:
      if event_name in self._listeners:
        listeners_to_call.extend(self._listeners[event_name])
      if event_name in self._listeners_once:
        once_listeners_to_call.extend(self._listeners_once[event_name])
        self._listeners_once[event_name].clear()

    if not listeners_to_call and not once_listeners_to_call:
      logger.debug(f"EMIT_NO_LISTENERS: '{event_name}'")
      return

    logger.info(
      f"EMIT: '{event_name}' (Listeners: {len(listeners_to_call) + len(once_listeners_to_call)})"
    )

    all_listeners = listeners_to_call + once_listeners_to_call
    tasks = [
      self._call_listener(listener, event_name, *args, **kwargs)
      for listener in all_listeners
    ]
    await asyncio.gather(*tasks, return_exceptions=False)

  async def _call_listener(
    self, listener: callable, event_name: str, *args, **kwargs
  ):
    try:
      await listener(*args, **kwargs)
    except Exception as e:
      logger.error(
        f"LISTENER_ERROR: {listener.__name__} on '{event_name}': {e}",
        exc_info=False
      )
