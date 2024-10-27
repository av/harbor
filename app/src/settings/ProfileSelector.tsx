import { IconButton } from "../IconButton";
import { IconCirclePlus } from "../Icons";
import { HarborConfig } from "../config/HarborConfig";
import { HarborConfigEditor } from "../config/HarborConfigEditor";
import { orderByPredefined } from "../utils";
import { CURRENT_PROFILE, EXTRA, SORT_ORDER } from "../configMetadata";
import { useSelectedProfile } from "../useSelectedProfile";
import { useOverlays } from "../OverlayContext";
import { ConfigNameModal } from "../config/ConfigNameModal";
import { useEffect } from "react";

export const ProfileSelector = (
    { configs }: { configs: HarborConfig[] },
) => {
    const overlays = useOverlays();
    const [selected, setSelected] = useSelectedProfile();

    const configMap = new Map(
        configs.map((config) => [config.profile.name, config]),
    );

    useEffect(() => {
        if (!configMap.has(selected)) {
            // We lost previously selected
            // profile in one way or another
            setSelected(CURRENT_PROFILE);
        }
    }, [configs]);

    const currentConfig = configMap.get(selected);
    const sorted = orderByPredefined(
        configs.map((c) => c.profile.name),
        SORT_ORDER,
    );

    const handleCreate = async () => {
        overlays.open(
            <ConfigNameModal
                key="config-name"
                onCreate={async (name) => {
                    const def = configs.find((c) => c.isDefault);
                    def?.saveAs(name);
                    setSelected(name);
                    overlays.close();
                    window.location.reload();
                }}
            />,
        );
    };

    return (
        <div className="flex flex-col gap-4">
            <div className="flex gap-4 items-center">
                <div role="tablist" className="tabs tabs-boxed overflow-x-auto">
                    {sorted.map(
                        (profileId) => {
                            const config = configMap.get(profileId)!;
                            const profile = config.profile;

                            const activeClass = profile.name === selected
                                ? "tab-active"
                                : "";
                            const name = EXTRA[profile.name]
                                ? EXTRA[profile.name].name
                                : profile.name;

                            return (
                                <a
                                    key={profile.name}
                                    role="tab"
                                    className={`tab ${activeClass}`}
                                    onClick={() => setSelected(profile.name)}
                                >
                                    {name}
                                </a>
                            );
                        },
                    )}
                </div>
                <div className="flex-1"></div>
                <IconButton
                    className="btn-md"
                    icon={<IconCirclePlus className="w-6 h-6" />}
                    onClick={handleCreate}
                />
            </div>

            {currentConfig && <HarborConfigEditor config={currentConfig} />}

            {!currentConfig && (
                <div className="rounded-box p-4 bg-base-200">
                    <span>Unexpected error loading configuration</span>
                </div>
            )}
        </div>
    );
};
