import { Dispatch, useCallback } from 'react';
import { useSharedState } from './useSharedState';
import * as localStorage from './localStorage';

const STORED_STATE_PREFIX = 'storedState:';
const getStoredKey = (key: string): string => `${STORED_STATE_PREFIX}${key}`;


export const useStoredState = <T extends unknown>(
    key: string,
    defaultValue: T,
): [T, Dispatch<T>] => {
    const [state, setState] = useSharedState(
        getStoredKey(key),
        () => localStorage.readLocalStorage(key, defaultValue),
    );

    const setStoredState = useCallback((newState: T) => {
        localStorage.writeLocalStorage(key, newState);
        setState(newState);
    }, [key, setState]);

    return [state, setStoredState];
};
