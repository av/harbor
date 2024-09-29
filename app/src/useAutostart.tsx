import { disable, enable, isEnabled } from "@tauri-apps/plugin-autostart";
import { useEffect, useState } from "react";

import { toasted } from "./utils";

export const useAutostart = () => {
    const [loading, setLoading] = useState(false);
    const [autostart, __setAutostart] = useState(false);

    useEffect(() => {
        const checkAutostart = async () => {
            try {
                setLoading(true);

                const enabled = await isEnabled();
                __setAutostart(enabled);
            } catch (e) {
                throw e;
            } finally {
                setLoading(false);
            }
        };

        toasted({
            action: checkAutostart,
            error: "Failed to check autostart",
        });
    }, []);

    const setAutostart = async (enabled: boolean) => {
        const action = async () => {
            try {
                setLoading(true);

                if (enabled) {
                    await enable();
                } else {
                    await disable();
                }

                __setAutostart(enabled);
            } catch (e) {
                throw e;
            } finally {
                setLoading(false);
            }
        };

        toasted({
            action,
            ok: `Autostart ${enabled ? "enabled" : "disabled"}`,
            error: `Failed to ${enabled ? "enable" : "disable"} autostart`,
        });
    };

    return {
        enabled: autostart,
        loading: loading,
        setAutostart,
    };
};
