import { Dispatch, SetStateAction, useCallback, useRef } from "react";

export type ArrayState<T> = {
    items: T[];
    setItems: Dispatch<SetStateAction<T[]>>;
    push: (item: T) => void;
    add: (item: T) => void;
    unshift: (item: T) => void;
    toggle: (item: T, on?: boolean) => void;
    remove: (item: T) => void;
    pop: () => T | undefined;
    shift: () => T | undefined;
    clear: () => void;
};

export const useArrayState = <T>(
    [items, setItems]: [T[], Dispatch<SetStateAction<T[]>>],
): ArrayState<T> => {
    // This helps with methods that
    // need to return their value immediately.
    const itemsRef = useRef(items);
    itemsRef.current = items;

    const push = useCallback(
        (item: T) => setItems((prev) => [...prev, item]),
        [],
    );
    const add = useCallback((item: T) => {
        const { current } = itemsRef;

        if (!current.includes(item)) {
            push(item);
        }
    }, []);
    const unshift = useCallback(
        (item: T) => setItems((prev) => [item, ...prev]),
        [],
    );
    const remove = useCallback(
        (item: T) =>
            setItems((prev) =>
                prev.filter((currentItem) => currentItem !== item)
            ),
        [],
    );
    const clear = useCallback(() => setItems([]), []);
    const toggle = useCallback((item: T, on?: boolean) => {
        const { current } = itemsRef;
        const include = on ?? !current.includes(item);

        if (include) {
            push(item);
        } else {
            remove(item);
        }
    }, []);

    const pop = useCallback(() => {
        const item = itemsRef.current.pop();

        if (item) {
            setItems([...itemsRef.current]);
        }

        return item;
    }, []);

    const shift = useCallback(() => {
        const item = itemsRef.current.shift();

        if (item) {
            setItems([...itemsRef.current]);
        }

        return item;
    }, []);

    return {
        items,
        setItems,
        push,
        add,
        pop,
        shift,
        unshift,
        toggle,
        remove,
        clear,
    };
};
