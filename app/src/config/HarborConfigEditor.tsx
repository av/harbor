import { Command } from "@tauri-apps/plugin-shell";

import { CURRENT_PROFILE, EXTRA, SECTIONS_ORDER } from "../configMetadata";
import { IconButton } from "../IconButton";
import {
    IconEraser,
    IconExternalLink,
    IconFiles,
    IconRocketLaunch,
    IconSave,
    IconTrash,
} from "../Icons";
import { HarborConfig, HarborConfigSection } from "./HarborConfig";
import { HarborConfigSectionEditor } from "./HarborConfigSectionEditor";
import { useOverlays } from "../OverlayContext";
import { ConfigNameModal } from "./ConfigNameModal";
import { useSelectedProfile } from "../useSelectedProfile";
import { Shortcuts, useGlobalKeydown } from "../useGlobalKeydown";
import { orderByPredefined, toasted } from "../utils";
import { ConfirmModal } from "../ConfirmModal";
import { SearchInput } from "../SearchInput";
import { useSearch } from "../useSearch";
import { ChangeEvent } from "react";

export const HarborConfigEditor = (
    { config }: { config: HarborConfig },
) => {
    config.use();

    const overlays = useOverlays();
    const [, setSelectedProfile] = useSelectedProfile();
    const search = useSearch("config");

    const maybeExtra = EXTRA[config.profile.name];
    const handleFileOpen = async () => {
        await Command.create("open", [config.profile.file]).execute();
    };

    const handleSave = async () => {
        await toasted({
            action: () => config.save(),
            ok: "Saved!",
            error: "Failed to save!",
        });
    };

    const handleApply = async () => {
        await toasted({
            action: () => config.apply(),
            ok: "Applied to Current!",
            error: "Failed to apply!",
        });
    };

    const handleSaveAs = async () => {
        overlays.open(
            <ConfigNameModal
                key="config-name"
                onCreate={async (name) => {
                    await config.saveAs(name);
                    setSelectedProfile(name);
                    overlays.close();
                    window.location.reload();
                }}
            />,
        );
    };

    const handleReset = async () => {
        overlays.open(
            <ConfirmModal
                key="confirm-reset"
                onConfirm={async () => {
                    await toasted({
                        action: () => config.reset(),
                        ok: "Reset to default",
                        error: "Failed to reset!",
                    });
                }}
            >
                <h2 className="text-2xl mb-2 font-bold">Reset to default?</h2>
                <p>This will reset all values to the default configuration.</p>
                <p>Are you sure?</p>
            </ConfirmModal>,
        );
    };

    const handleDelete = async () => {
        overlays.open(
            <ConfirmModal
                key="confirm-delete"
                onConfirm={async () => {
                    await config.delete();
                    setSelectedProfile(CURRENT_PROFILE);
                    window.location.reload();
                }}
            >
                <h2 className="text-2xl mb-2 font-bold">Delete?</h2>
                <p>This will permanently delete this profile.</p>
                <p>Are you sure?</p>
            </ConfirmModal>,
        );
    };

    const canApply = !config.isCurrent;
    const canSave = !config.isDefault;
    const canReset = !config.isDefault;
    const canDelete = !(config.isDefault || config.isCurrent);

    useGlobalKeydown(Shortcuts.save, (e) => {
        e.preventDefault();

        if (canSave) {
            handleSave();
        }
    });

    const sectionMap = new Map<string, HarborConfigSection>(
        config.sections.map((section) => [section.name, section]),
    );
    const sortedSections = orderByPredefined(
        Array.from(sectionMap.keys()),
        SECTIONS_ORDER,
    );

    return (
        <>
            <ul className="menu menu-horizontal bg-base-300/50 rounded-box max-w-2xl text-xl sticky top-4 z-10 text-base-content/80 backdrop-blur items-center gap-4">
                {canApply && (
                    <li
                        className="tooltip tooltip-bottom"
                        data-tip="Apply to Current"
                    >
                        <a onClick={handleApply}>
                            <IconRocketLaunch />
                        </a>
                    </li>
                )}
                {canSave && (
                    <li className="tooltip tooltip-bottom" data-tip="Save (Ctrl+S)">
                        <a onClick={handleSave}>
                            <IconSave />
                        </a>
                    </li>
                )}
                <li
                    className="tooltip tooltip-bottom"
                    data-tip="Save as new custom profile"
                >
                    <a onClick={handleSaveAs}>
                        <IconFiles />
                    </a>
                </li>
                {canReset && (
                    <li
                        className="tooltip tooltip-bottom"
                        data-tip="Reset to defaults"
                    >
                        <a onClick={handleReset}>
                            <IconEraser />
                        </a>
                    </li>
                )}
                {canDelete && (
                    <li className="tooltip tooltip-bottom" data-tip="Delete">
                        <a onClick={handleDelete}>
                            <IconTrash />
                        </a>
                    </li>
                )}

                <div className="flex-1"></div>

                <SearchInput
                    defaultValue={search.query}
                    onChange={(e: ChangeEvent<HTMLInputElement>) =>
                        search.setQuery(e.target.value)}
                />
            </ul>

            {maybeExtra && (
                <div className="rounded-box bg-base-200 p-4 max-w-2xl">
                    <h2 className="text-2xl mb-2 font-bold">
                        {maybeExtra.name}
                    </h2>
                    <p>{maybeExtra.content}</p>
                </div>
            )}

            {!config.isReadonly && (
                <div className="flex gap-2 items-center rounded-box p-4 bg-base-200 max-w-2xl">
                    <pre className="break-all overflow-hidden">{config.profile.file}</pre>
                    <div className="flex-1"></div>
                    <IconButton
                        className="text-xl text-base-content/30"
                        icon={<IconExternalLink />}
                        onClick={handleFileOpen}
                    />
                </div>
            )}

            {sortedSections.map((sectionId) => {
                const section = sectionMap.get(sectionId)!;

                return (
                    <HarborConfigSectionEditor
                        key={section.name}
                        section={section}
                    />
                );
            })}

            <div className="collapse collapse-arrow bg-base-200 max-w-2xl">
                <input type="checkbox" />
                <div className="collapse-title text-2xl font-bold">Source</div>
                <div className="collapse-content rounded-box">
                    <pre className="overflow-auto">{config?.profile.content}</pre>
                </div>
            </div>
        </>
    );
};
