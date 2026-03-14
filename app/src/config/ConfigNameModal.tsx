import { useState } from "react";

import { Modal } from "../Modal";
import { useOverlays } from "../OverlayContext";
import { validate } from "../utils";
import { useCalled } from "../useCalled";
import { KEY_CODES, useGlobalKeydown } from "../useGlobalKeydown";

const validProfileName = (value: string) => {
    if (value.length === 0) {
        return "The value should not be empty";
    }
    if (value.length > 64) {
        return "The name must be 64 characters or fewer";
    }
    if (!/^[a-zA-Z0-9_-]+$/.test(value)) {
        return "Only letters, numbers, hyphens, and underscores are allowed";
    }
};

export const ConfigNameModal = ({
    onCreate,
}: {
    onCreate: (name: string) => void;
}) => {
    const { close } = useOverlays();
    const [name, setName] = useState("");

    const maybeError = validate(name, [
        validProfileName,
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
                        Letters, numbers, hyphens, underscores only
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
