import { ReactNode } from "react";

export type HarborProfile = {
    name: string;
    file: string;
    content: string;
};

export enum HarborConfigType {
    string = "string",
    number = "number",
    boolean = "boolean",
    array = "array",
    dict = "dict",
}

export const CURRENT_PROFILE = "__current";
export const DEFAULT_PROFILE = "default";

export const HARBOR_PREFIX = "HARBOR_";
export const PROFILES_DIR = "profiles";

export const EXTRA: Record<string, {
    name: string;
    content: React.ReactNode;
}> = {
    [DEFAULT_PROFILE]: {
        name: "Default",
        content: (
            <>
                <span>
                    Defaults from the current Harbor CLI. Save as a new profile
                    to edit.
                </span>
            </>
        ),
    },
    [CURRENT_PROFILE]: {
        name: "Current",
        content: (
            <>
                <span>This is current Harbor configuration.{" "}</span>
                <span>Edits are independent from the source profile.</span>
            </>
        ),
    },
};

export const SORT_ORDER = [
    CURRENT_PROFILE,
    DEFAULT_PROFILE,
];

export const SECTIONS_ORDER = [
    "LLAMACPP",
    "VLLM",
    "SERVICES",
    "LOG",
    "HISTORY",
    "WEBUI",
];

export const SECTIONS_EXTRA: Partial<Record<string, { content: ReactNode }>> = {
    UI: {
        content: (
            <>
                <span>
                    Main Frontend, Autoopen
                </span>
            </>
        ),
    }
};
