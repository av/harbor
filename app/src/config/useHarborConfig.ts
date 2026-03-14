import { useEffect, useState } from "react";
import { readDir, readTextFile } from "@tauri-apps/plugin-fs";
import { join } from "@tauri-apps/api/path";

import { resolveHarborHome, resolveProfilesDir } from "../useHarbor";
import { HarborConfig } from "./HarborConfig";
import { CURRENT_PROFILE } from "../configMetadata";
import { useSharedState } from "../useSharedState";

export const useHarborConfig = () => {
    const [configs, setConfigs] = useState<HarborConfig[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<unknown | null>(null);
    const [configVersion] = useSharedState("configVersion", 0);

    useEffect(() => {
        let cancelled = false;

        async function readProfiles() {
            HarborConfig.cache.clear();

            try {
                setLoading(true);

                const homeDir = await resolveHarborHome();
                const profilesDir = await resolveProfilesDir();
                const files = await readDir(profilesDir);

                const targets = await Promise.all(
                    files
                        .filter((entry) => {
                            return entry.isFile && entry.name.endsWith(".env");
                        })
                        .map(async (entry) => {
                            return {
                                ...entry,
                                path: await join(profilesDir, entry.name),
                            };
                        }),
                );

                targets.push({
                    name: `${CURRENT_PROFILE}.env`,
                    path: await join(homeDir, ".env"),
                    isFile: true,
                    isDirectory: false,
                    isSymlink: false,
                });

                const configs = await Promise.all(
                    targets
                        .map(async (profile) => {
                            const content = await readTextFile(profile.path);

                            return HarborConfig.cached({
                                name: profile.name.replace(".env", ""),
                                file: profile.path,
                                content,
                            });
                        }),
                );

                if (!cancelled) {
                    setConfigs(configs);
                }
            } catch (error: unknown) {
                if (!cancelled) {
                    console.error(error);
                    setError(error);
                }
            } finally {
                if (!cancelled) {
                    setLoading(false);
                }
            }
        }

        readProfiles();

        return () => {
            cancelled = true;
        };
    }, [configVersion]);

    return {
        configs,
        loading,
        error,
    };
};
