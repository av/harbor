import { useContext } from "react";
import { ModelEntry } from "./ModelEntry";
import { ModelsContext } from "./ModelsContext";

export type ModelsStatus = "idle" | "loading" | "ok" | "error";

export interface UseModelsResult {
    models: ModelEntry[];
    status: ModelsStatus;
    error: string | null;
    reload: () => void;
}

export function useModels(): UseModelsResult {
    const context = useContext(ModelsContext);

    if (!context) {
        throw new Error("useModels must be used within a ModelsProvider");
    }

    return context;
}
