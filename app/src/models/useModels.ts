import { useState, useCallback, useEffect } from "react";
import { runHarbor } from "../useHarbor";
import { ModelEntry, parseModels } from "./ModelEntry";

export type ModelsStatus = "idle" | "loading" | "ok" | "error";

export interface UseModelsResult {
    models: ModelEntry[];
    status: ModelsStatus;
    error: string | null;
    reload: () => void;
}

const DOCKER_ERROR_SIGNALS = [
    "Cannot connect to the Docker daemon",
    "docker: not found",
    "Is the docker daemon running",
];

function isDockerError(msg: string): boolean {
    return DOCKER_ERROR_SIGNALS.some((s) => msg.includes(s));
}

export function useModels(): UseModelsResult {
    const [models, setModels] = useState<ModelEntry[]>([]);
    const [status, setStatus] = useState<ModelsStatus>("idle");
    const [error, setError] = useState<string | null>(null);

    const reload = useCallback(async () => {
        setStatus("loading");
        setError(null);

        try {
            const result = await runHarbor(["models", "ls", "--json"]);
            const raw = (result.stdout ?? "").trim();
            const errOut = (result.stderr ?? "").trim();

            if (isDockerError(errOut)) {
                setError("Docker is not running. Start Docker and retry.");
                setStatus("error");
                return;
            }

            if (!raw) {
                setModels([]);
                setStatus("ok");
                return;
            }

            const parsed = parseModels(raw);
            setModels(parsed);
            setStatus("ok");
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            setError(isDockerError(msg) ? "Docker is not running. Start Docker and retry." : msg);
            setStatus("error");
        }
    }, []);

    useEffect(() => {
        reload();
    }, [reload]);

    return { models, status, error, reload };
}
