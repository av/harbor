import { useState } from "react";

import { Modal } from "../Modal";
import { useOverlays } from "../OverlayContext";
import { noSpaces, notEmpty, validate } from "../utils";
import { useCalled } from "../useCalled";
import { KEY_CODES, useGlobalKeydown } from "../useGlobalKeydown";

export const ConfigNameModal = ({
    onCreate,
}: {
    onCreate: (name: string) => void;
}) => {
    const { close } = useOverlays();
    const [name, setName] = useState("");

    const maybeError = validate(name, [
        notEmpty,
        noSpaces,
    ]);
    const handleNameChange = useCalled((e) => {
        setName(e.target.value);
    });

    const canCreate = !maybeError;
    useGlobalKeydown({ key: KEY_CODES.ENTER }, () => {
        if (canCreate) {
            onCreate(name);
        }
    });

    return (
        <Modal>
            <h3 className="font-bold text-lg">Name your new profile</h3>
            <p className="mt-4">
                <div className="label gap-2">
                    <div className="label-text">Name</div>
                    <div className="label-text-alt text-right text-base-content/50">
                        Consider something easy to type
                    </div>
                </div>
                <input
                    type="text"
                    ref={el => el?.focus()}
                    placeholder="Type here"
                    onChange={handleNameChange}
                    className="input input-bordered w-full"
                />
                <div className="label">
                    {maybeError && handleNameChange.called && (
                        <div className="label-text-alt text-error">
                            {maybeError}
                        </div>
                    )}
                </div>
            </p>
            <div className="modal-action">
                <button className="btn" onClick={() => close()}>Cancel</button>
                <div className="flex-1"></div>
                <button
                    className="btn btn-primary"
                    onClick={() => onCreate(name)}
                    disabled={!canCreate}
                >
                    Create
                </button>
            </div>
        </Modal>
    );
};
