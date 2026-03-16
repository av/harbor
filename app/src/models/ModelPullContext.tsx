import { createContext, FC, PropsWithChildren, useCallback, useContext, useMemo, useState } from "react";
import { useHarborStream, type HarborStreamCompletion, type HarborStreamCompletionStatus } from "../service/useHarborStream";
import { useModels } from "./useModels";

export type ModelPullSessionStatus = "idle" | "running" | HarborStreamCompletionStatus;

export interface ModelPullSession {
    modelName: string;
    command: string[];
    lines: string[];
    chunks: Uint8Array[];
    bufferVersion: number;
    error: string | null;
    status: ModelPullSessionStatus;
    completion: HarborStreamCompletion | null;
    isActive: boolean;
    canCancel: boolean;
}

export interface ModelPullContextValue {
    session: ModelPullSession | null;
    startPull: (modelName: string) => void;
    cancelPull: () => void;
    dismissSession: () => void;
}

const ModelPullContext = createContext<ModelPullContextValue | null>(null);

export const ModelPullProvider: FC<PropsWithChildren> = ({ children }) => {
    const { reload } = useModels();
    const [modelName, setModelName] = useState<string | null>(null);
    const [dismissedAtGeneration, setDismissedAtGeneration] = useState(0);
    const [sessionGeneration, setSessionGeneration] = useState(0);

    const pullStream = useHarborStream(["models", "pull"], {
        onComplete: () => {
            reload();
        },
        appendExitMessage: false,
        raw: true,
    });

    const startPull = useCallback((nextModelName: string) => {
        const trimmed = nextModelName.trim();
        if (!trimmed) return;

        setDismissedAtGeneration(0);
        setModelName(trimmed);
        setSessionGeneration((previous) => previous + 1);
        pullStream.start(["models", "pull", trimmed]);
    }, [pullStream]);

    const cancelPull = useCallback(() => {
        pullStream.stop();
    }, [pullStream]);

    const dismissSession = useCallback(() => {
        if (pullStream.isStreaming) {
            return;
        }

        setDismissedAtGeneration(sessionGeneration);
    }, [pullStream.isStreaming, sessionGeneration]);

    const session = useMemo<ModelPullSession | null>(() => {
        if (!modelName || dismissedAtGeneration === sessionGeneration) {
            return null;
        }

        const status: ModelPullSessionStatus = pullStream.isStreaming
            ? "running"
            : pullStream.completion?.status ?? "idle";

        return {
            modelName,
            command: ["models", "pull", modelName],
            lines: pullStream.lines,
            chunks: pullStream.chunks,
            bufferVersion: pullStream.bufferVersion,
            error: pullStream.error,
            status,
            completion: pullStream.completion,
            isActive: pullStream.isStreaming,
            canCancel: pullStream.isStreaming,
        };
    }, [dismissedAtGeneration, modelName, pullStream.bufferVersion, pullStream.chunks, pullStream.completion, pullStream.error, pullStream.isStreaming, pullStream.lines, sessionGeneration]);

    const value = useMemo<ModelPullContextValue>(() => ({
        session,
        startPull,
        cancelPull,
        dismissSession,
    }), [cancelPull, dismissSession, session, startPull]);

    return <ModelPullContext.Provider value={value}>{children}</ModelPullContext.Provider>;
};

export function useModelPull(): ModelPullContextValue {
    const context = useContext(ModelPullContext);

    if (!context) {
        throw new Error("useModelPull must be used within a ModelPullProvider");
    }

    return context;
}
