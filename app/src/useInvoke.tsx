import { useState, useEffect, useCallback } from 'react';
import { invoke } from '@tauri-apps/api/core';

interface InvokeOptions<T> {
  command: string;
  args?: Record<string, unknown>;
  onSuccess?: (data: T) => void;
  onError?: (error: Error) => void;
}

function useInvoke<T>({ command, args = {}, onSuccess, onError }: InvokeOptions<T>) {
  const [data, setData] = useState<T | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const executeInvoke = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const result = await invoke<T>(command, args);
      setData(result);
      onSuccess?.(result);
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      setError(error);
      onError?.(error);
    } finally {
      setIsLoading(false);
    }
  }, [command, args, onSuccess, onError]);

  useEffect(() => {
    executeInvoke();
  }, [executeInvoke]);

  const refetch = useCallback(() => {
    executeInvoke();
  }, [executeInvoke]);

  return { data, isLoading, error, refetch };
}

export default useInvoke;
