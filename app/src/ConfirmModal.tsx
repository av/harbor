import { Modal } from "./Modal";
import { useOverlays } from "./OverlayContext";
import { KEY_CODES, useGlobalKeydown } from "./useGlobalKeydown";

export const ConfirmModal = ({
    onConfirm,
    children,
}: {
    onConfirm: () => void;
    children: React.ReactNode;
}) => {
    const { close } = useOverlays();
    const handleConfirm = () => {
        onConfirm();
        close();
    };

    useGlobalKeydown({ key: KEY_CODES.ENTER }, () => {
        handleConfirm();
    });

    return (
        <Modal>
            {children}
            <div className="modal-action">
                <button className="btn" onClick={() => close()}>
                    Cancel
                </button>
                <div className="flex-1"></div>
                <button className="btn btn-primary" onClick={handleConfirm}>
                    Confirm
                </button>
            </div>
        </Modal>
    );
}