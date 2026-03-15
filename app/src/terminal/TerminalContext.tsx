import { createContext, FC, MutableRefObject, ReactNode, useCallback, useContext, useRef, useState } from "react";

interface TerminalContextValue {
    isOpen: boolean;
    open: () => void;
    close: () => void;
    toggle: () => void;
    /** Ref that TerminalPanel sets to its xterm focus function after mount. */
    focusRef: MutableRefObject<(() => void) | null>;
    /** Opens the panel and focuses the terminal input (deferred by one frame). */
    openAndFocus: () => void;
}

const noop = () => {};
const noopRef: MutableRefObject<(() => void) | null> = { current: null };

const TerminalContext = createContext<TerminalContextValue>({
    isOpen: false,
    open: noop,
    close: noop,
    toggle: noop,
    focusRef: noopRef,
    openAndFocus: noop,
});

export const TerminalProvider: FC<{ children: ReactNode }> = ({ children }) => {
    const [isOpen, setIsOpen] = useState(false);
    const focusRef = useRef<(() => void) | null>(null);
    const open = useCallback(() => setIsOpen(true), []);
    const close = useCallback(() => setIsOpen(false), []);
    const toggle = useCallback(() => setIsOpen((v) => !v), []);
    const openAndFocus = useCallback(() => {
        setIsOpen(true);
        // Defer focus so the panel has time to expand and xterm to become visible
        setTimeout(() => focusRef.current?.(), 0);
    }, []);
    return (
        <TerminalContext.Provider value={{ isOpen, open, close, toggle, focusRef, openAndFocus }}>
            {children}
        </TerminalContext.Provider>
    );
};

export const useTerminalPanel = () => useContext(TerminalContext);
