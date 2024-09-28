import { useRef } from "react";

type Callable = (...args: any[]) => any;

export const useCalled = (fn: Callable): Callable & { called: boolean } => {
    const calledRef = useRef(false);
    const callProxy = (...args: any[]) => {
        const result = fn(...args);
        calledRef.current = true;
        return result;
    };

    return Object.assign(callProxy, {
        get called() {
            return calledRef.current;
        },
    });
};
