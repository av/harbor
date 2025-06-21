import asyncio


class AsyncDebouncer:
  """
    An asyncio-native debouncer.
    """

  def __init__(self, delay, target_coro):
    self._delay = delay    # Delay in seconds
    self._target_coro = target_coro    # The coroutine to call
    self._task = None
    self._args = None
    self._kwargs = None
    self.__name__ = f"AsyncDebouncer({self._target_coro.__name__}, {self._delay})"

  async def __call__(self, *args, **kwargs):
    """
        Call the debouncer with arguments for the target coroutine.
        This method is a coroutine itself but typically you might not await it
        directly in the message handler loop if you want the loop to proceed immediately.
        Instead, it schedules the debounced call.
        """
    if self._task is not None and not self._task.done():
      self._task.cancel()    # Cancel the previous task

    self._args = args
    self._kwargs = kwargs
    self._task = asyncio.create_task(self._schedule_fire())
    try:
      await asyncio.sleep(0)
    except asyncio.CancelledError:
      if self._task is not None and not self._task.done():
        self._task.cancel()
      raise

  async def _schedule_fire(self):
    """
        Waits for the delay and then executes the target coroutine.
        """
    try:
      await asyncio.sleep(self._delay)
      if self._args is not None or self._kwargs is not None:
        await self._target_coro(*self._args, **self._kwargs)
      else:
        await self._target_coro()
    except asyncio.CancelledError:
      pass

  def cancel(self):
    """
        Cancel any pending debounced call.
        """
    if self._task is not None and not self._task.done():
      self._task.cancel()
      self._task = None
