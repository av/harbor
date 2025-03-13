import { useMemo } from "react";

import { resolveHarborHome, useHarbor } from "../useHarbor";
import { HarborService, serviceMetadata } from "../serviceMetadata";
import { resolveResultLines } from "../utils";
import { homeDir, join } from "@tauri-apps/api/path";
import { readTextFile, BaseDirectory } from "@tauri-apps/plugin-fs";
import { marked } from "marked";

export const isCoreService = (handle: string) => {
    return !handle.includes('-');
}

async function fetchDocs(wikiUrl: string | undefined): Promise<string | undefined> {
    if (wikiUrl === undefined || wikiUrl === "") {
        return undefined;
    }
    const docPath = wikiUrl.split("/").pop()?.replace(':', '&colon') + ".md";
    const harborHome = await resolveHarborHome();
    const home = await homeDir();
    const relative = harborHome.replace(home + '/', "");

    const content = await readTextFile(await join(relative, "docs", docPath!), { baseDir: BaseDirectory.Home });
    const tokens = marked.lexer(content, { gfm: true });
    let overview = "";
    const startToken = tokens.find((token) => token.type === "heading" && token.depth === 4 && token.text === "Overview");
    if (!startToken) {
        return undefined;
    }

    let startIndex = tokens.indexOf(startToken) + 1;
    while (startIndex < tokens.length && tokens[startIndex].type !== "heading" && tokens[startIndex].type !== "hr") {
        overview += tokens[startIndex].raw;
        startIndex++;
    }
    return overview;
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
                shortDoc: fetchDocs(maybeMetadata.wikiUrl),
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