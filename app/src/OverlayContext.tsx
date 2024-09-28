import { createContext, ReactNode, useContext, useMemo, useState } from "react";
import { useArrayState } from "./useArrayState";

export type Overlay = ReactNode;

interface OverlayContextProps {
    open: (props: Overlay) => void;
    close: (name?: string) => void;
    opened: number;
    closeAll: () => void;
}

export const OverlayContext = createContext<OverlayContextProps>({
    open: (_props: Overlay) => {},
    close: () => {},
    opened: 0,
    closeAll: () => {},
});

export const OverlayProvider = ({ children }: { children: ReactNode }) => {
    const overlays = useArrayState(useState<Array<Overlay>>([]));
    const value = useMemo<OverlayContextProps>(
        () => ({
            open: (overlay: Overlay) => {
                overlays.push(overlay);
            },
            close: () => {
                overlays.pop();
            },
            opened: overlays.items.length,
            closeAll: () => overlays.clear(),
        }),
        [overlays],
    );

    return (
        <OverlayContext.Provider value={value}>
            {children}
            {overlays.items.map<ReactNode>((modal) => modal)}
        </OverlayContext.Provider>
    );
};

export const useOverlays = () => useContext(OverlayContext);
