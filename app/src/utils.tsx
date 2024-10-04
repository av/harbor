import toast from "react-hot-toast";
import { IconCheck, IconOctagonAlert } from "./Icons";

type Message = Parameters<typeof toast>[0];

export const toasted = async ({
    action,
    ok,
    error,
    finally: finFn,
}: {
    action: () => Promise<any>;
    finally?: () => void;
    ok?: Message;
    error: Message;
}) => {
    try {
        await action();

        if (ok) {
            toast(ok, { icon: <IconCheck /> });
        }
    } catch (e) {
        console.error(e);
        toast.error(error, { icon: <IconOctagonAlert /> });
        return;
    } finally {
        if (finFn) {
            finFn();
        }
    }
};

export const once = <T extends unknown>(fn: () => T) => {
    let value: T;

    return () => {
        if (value === undefined) {
            value = fn();
        }

        return value;
    };
};

export const orderByPredefined = <T extends unknown>(arr: T[], order: T[]) => {
    return arr.sort((a: T, b: T) => {
        const aIndex = order.indexOf(a);
        const bIndex = order.indexOf(b);

        if (aIndex === -1 && bIndex === -1) {
            return `${a}`.localeCompare(`${b}`);
        }

        if (aIndex === -1) {
            return 1;
        }

        if (bIndex === -1) {
            return -1;
        }

        return aIndex - bIndex;
    });
};

// Undefined - all good
// String - error message
type Validator<T> = (value: T) => string | undefined;

export const validate = <T,>(
    value: T,
    validators: Validator<T>[] = [],
) => {
    for (const validator of validators) {
        const error = validator(value);

        if (error) {
            return error;
        }
    }
};

export const notEmpty = (value: string) => {
    if (value.length === 0) {
        return "The value should not be empty";
    }
};

export const noSpaces = (value: string) => {
    if (value.includes(" ")) {
        return "The value should not contain spaces";
    }
};

export type DebounceOptions = {
    leading?: boolean
    trailing?: boolean
    maxWait?: number
}

export type ControlFunctions = {
    (...args: any): any
    cancel: () => void
    flush: () => void
}

export const debounce = <T extends (...args: any) => ReturnType<T>>(
    func: T,
    wait: number,
    options?: DebounceOptions,
): ControlFunctions => {
    let timeout: number | undefined;

    const debounced = (...args: Parameters<T>) => {
        const later = () => {
            timeout = undefined;
            func(...args);
        };

        const callNow = options?.leading && !timeout;
        if (timeout) {
            clearTimeout(timeout);
        }

        timeout = setTimeout(later, wait);

        if (callNow) {
            func(...args);
        }
    };

    debounced.cancel = () => {
        if (timeout) {
            clearTimeout(timeout);
        }
    };

    debounced.flush = () => {
        if (timeout) {
            clearTimeout(timeout);
            func();
        }
    };

    return debounced;
}