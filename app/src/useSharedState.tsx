import {
    Dispatch,
    SetStateAction,
    useCallback,
    useEffect,
    useState,
} from "react";

export type StateKey = string | symbol;
export type StateEntry<T> = {
    value: T;
    hooks: Set<Dispatch<SetStateAction<T>>>;
};
type DefaultValue<T> = T | (() => T);

declare global {
    var __sharedStates: Map<StateKey, StateEntry<unknown>> | undefined;
}

const getSharedStates = (): Map<StateKey, StateEntry<unknown>> => {
    if (!globalThis.__sharedStates) {
        globalThis.__sharedStates = new Map<StateKey, StateEntry<unknown>>();
    }

    return globalThis.__sharedStates as Map<StateKey, StateEntry<unknown>>;
};

export const states = getSharedStates();

export const useSharedState = <T,>(
    key: StateKey,
    defaultValue: DefaultValue<T>,
    preserveCleanup?: boolean,
): [T, Dispatch<SetStateAction<T>>] => {
    setDefaultValue<T>(key, defaultValue);

    const current = getCurrentValue<T>(key, defaultValue);
    const state = useState<T>(current.value);
    const setState = useCallback(getKeyedSetState<T>(key), [key]);
    current.hooks.add(state[1]);

    useEffect(
        () => {
            current.hooks.add(state[1]);
            return function cleanup() {
                current.hooks.delete(state[1]);
                if (current.hooks.size === 0 && !preserveCleanup) {
                    states.delete(key);
                }
            };
        },
        [key, preserveCleanup],
    );

    return [state[0], setState];
};

const update = <T,>(key: StateKey, value: SetStateAction<T>) => {
    updateValue<T>(key, value);
    emitUpdate<T>(key);
};

const emitUpdate = <T,>(key: StateKey) => {
    const current = getCurrentValue<T>(key);
    current.hooks.forEach((hook) => hook(current.value!));
};

const getCurrentValue = <T,>(
    key: StateKey,
    defaultValue?: DefaultValue<T>,
): StateEntry<T> => {
    if (!states.has(key)) {
        states.set(key, {
            value: defaultValue instanceof Function
                ? defaultValue()
                : defaultValue,
            hooks: new Set<Dispatch<SetStateAction<unknown>>>(),
        });
    }

    return states.get(key) as StateEntry<T>;
};

const getKeyedSetState =
    <T,>(key: StateKey): Dispatch<SetStateAction<T>> =>
    (value: SetStateAction<T>) => {
        update<T>(key, value);
    };

const setDefaultValue = <T,>(key: StateKey, defaultValue: DefaultValue<T>) => {
    const current = getCurrentValue<T>(key, defaultValue);

    if (current.value === undefined && defaultValue !== undefined) {
        updateValue<T>(key, defaultValue);
    }
};

const updateValue = <T,>(key: StateKey, value: SetStateAction<T>) => {
    const current = getCurrentValue<T>(key);
    let newValue = value;

    if (typeof newValue === "function") {
        const updater = newValue as (prev: T) => T;
        newValue = updater(current.value);
    }

    if (current.value === newValue) {
        return;
    }

    current.value = newValue;
};
