import { useEffect, useRef } from "react";

export const KEY_CODES = {
    ESC: "Escape",
    ENTER: "Enter",
    S: "s",
};

type KeyMatch = {
    key: string;
    ctrlKey?: boolean;
    shiftKey?: boolean;
    metaKey?: boolean;
    altKey?: boolean;
};

export const matches = (event: KeyboardEvent, match: KeyMatch) => {
    return (
        event.key === match.key &&
        event.ctrlKey === !!match.ctrlKey &&
        event.shiftKey === !!match.shiftKey &&
        event.metaKey === !!match.metaKey &&
        event.altKey === !!match.altKey
    );
};

export const useGlobalKeydown = (
    matcher: KeyMatch | KeyMatch[],
    callback: (e: KeyboardEvent) => void,
) => {
    const matchers = Array.isArray(matcher) ? matcher : [matcher];
    const cbRef = useRef(callback);

    cbRef.current = callback;

    useEffect(() => {
        const handler = (event: KeyboardEvent) => {
            if (matchers.some((m) => matches(event, m))) {
                cbRef.current(event);
            }
        };

        document.addEventListener("keydown", handler);
        return () => {
            document.removeEventListener("keydown", handler);
        };
    }, []);
};
