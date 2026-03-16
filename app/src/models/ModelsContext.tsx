import { createContext, FC, PropsWithChildren, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { runHarbor } from "../useHarbor";
import { ModelEntry, parseModels } from "./ModelEntry";
import type { ModelsStatus, UseModelsResult } from "./useModels";

const DOCKER_ERROR_SIGNALS = [
    "Cannot connect to the Docker daemon",
    "docker: not found",
    "Is the docker daemon running",
];

function isDockerError(msg: string): boolean {
    return DOCKER_ERROR_SIGNALS.some((signal) => msg.includes(signal));
}

export const ModelsContext = createContext<UseModelsResult | null>(null);

export const ModelsProvider: FC<PropsWithChildren> = ({ children }) => {
    const [models, setModels] = useState<ModelEntry[]>([]);
    const [status, setStatus] = useState<ModelsStatus>("idle");
    const [error, setError] = useState<string | null>(null);
    const latestRequestIdRef = useRef(0);

    const reload = useCallback(() => {
        const requestId = ++latestRequestIdRef.current;

        setStatus("loading");
        setError(null);

        void (async () => {
            try {
                const result = await runHarbor(["models", "ls", "--json"]);

                if (requestId !== latestRequestIdRef.current) {
                    return;
                }

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

                setModels(parseModels(raw));
                setStatus("ok");
            } catch (e) {
                if (requestId !== latestRequestIdRef.current) {
                    return;
                }

                const msg = e instanceof Error ? e.message : String(e);
                setError(isDockerError(msg) ? "Docker is not running. Start Docker and retry." : msg);
                setStatus("error");
            }
        })();
    }, []);

    useEffect(() => {
        reload();
    }, [reload]);

    const value = useMemo<UseModelsResult>(() => ({
        models,
        status,
        error,
        reload,
    }), [error, models, reload, status]);

    return <ModelsContext.Provider value={value}>{children}</ModelsContext.Provider>;
};
