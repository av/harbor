import { ReactNode } from "react";
import { useOverlays } from "./OverlayContext";
import { KEY_CODES, useGlobalKeydown } from "./useGlobalKeydown";

export const Modal = ({ children }: { children: ReactNode }) => {
    const { close } = useOverlays();

    useGlobalKeydown({ key: KEY_CODES.ESC }, () => {
        close();
    });

    return (
        <>
            <dialog className="modal modal-open bg-base-300/50 backdrop-blur">
                <div className="modal-box">
                    {children}
                </div>
                <form
                    method="dialog"
                    className="modal-backdrop"
                    onClick={() => close()}
                >
                </form>
            </dialog>
        </>
    );
};
