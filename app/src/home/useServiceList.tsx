import { useMemo } from "react";

import { useHarbor } from "../useHarbor";
import { HarborService, serviceMetadata } from "../serviceMetadata";
import { resolveResultLines } from "../utils";

export const isCoreService = (handle: string) => {
    return !handle.includes('-');
}

export const useServiceList = () => {
    const [
        all,
        running,
        defaults,
    ] = [
            useHarbor(['ls']),
            useHarbor(['ls', '-a']),
            useHarbor(['defaults']),
        ]

    const services: HarborService[] = useMemo(() => {
        const runningResult = resolveResultLines(running.result)
        const defaultsResult = resolveResultLines(defaults.result)

        return resolveResultLines(all.result).filter(s => s.trim()).sort().map(line => {
            const handle = line.trim();
            const maybeMetadata = serviceMetadata[handle] ?? {};

            return {
                handle,
                isRunning: runningResult.includes(handle) ?? false,
                isDefault: defaultsResult.includes(handle) ?? false,
                tags: [],
                ...maybeMetadata,
            };
        }).filter((s) => isCoreService(s.handle)) ?? [];
    }, [all.result, running.result, defaults.result]);

    const rerun = () => {
        all.rerun();
        running.rerun();
    }

    return {
        services,
        loading: all.loading || running.loading || defaults.loading,
        error: all.error || running.error || defaults.error,
        rerun,
    };
}