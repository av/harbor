import { CURRENT_PROFILE } from "./configMetadata";
import { useStoredState } from "./useStoredState";

export const useSelectedProfile = () => {
    return useStoredState(
        "selectedProfile",
        CURRENT_PROFILE,
    );
};
