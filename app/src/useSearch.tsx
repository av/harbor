import { useCallback, useRef } from 'react';
import { useDebounceCallback } from './useDebounceCallback';
import { useSharedState } from './useSharedState';

export const useSearch = (id: string) => {
  const [query, setQuery] = useSharedState(`search.${id}`, '', true);
  const queryRef = useRef(query);

  queryRef.current = query.trim().toLocaleLowerCase();

  const setQueryQb = useCallback((newValue: string) => {
    setQuery(newValue);
  }, []);

  const debouncedSetQuery = useDebounceCallback(setQueryQb, 350);

  const matches = useCallback((str: string) => {
    if (queryRef.current === '') {
      return true;
    }

    return str.toLowerCase().includes(queryRef.current);
  }, []);

  return {
    query,
    setQuery: debouncedSetQuery,
    matches,
  }
}