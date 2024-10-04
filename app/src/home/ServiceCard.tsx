import { useState } from "react";
import { IconButton } from "../IconButton";
import {
    IconAudioLines,
    IconAward,
    IconBandage,
    IconExternalLink,
} from "../Icons";
import { ACTION_ICONS, HarborService, HST, HSTColorOpts, HSTColors } from "../serviceMetadata";
import { runHarbor } from "../useHarbor";
import { toasted } from "../utils";

const TAG_ADORNMENTS: Partial<Record<HST, React.ReactNode>> = {
    [HST.partial]: (
        <span className="mr-1 text-base-content/40">
            <IconBandage />
        </span>
    ),
    [HST.builtIn]: (
        <span className="mr-1 text-base-content/40">
            <IconAward />
        </span>
    ),
    [HST.audio]: (
        <span className="mr-1 text-base-content/40">
            <IconAudioLines />
        </span>
    ),
};

export const ServiceCard = (
    { service, onUpdate }: { service: HarborService; onUpdate: () => void },
) => {
    const [loading, setLoading] = useState(false);

    const openService = () => {
        runHarbor(["open", service.handle]);
    };

    const toggleService = () => {
        const msg = (str: string) => (
            <span>
                <span className="font-bold mr-2">{service.handle}</span>
                <span>{str}</span>
            </span>
        );

        const action = () => {
            setLoading(true);
            return runHarbor([
                service.isRunning ? "down" : "up",
                service.handle,
            ]);
        };
        const ok = service.isRunning ? msg("stopped") : msg("started");
        const error = service.isRunning
            ? msg("failed to stop")
            : msg("failed to start");

        toasted({
            action,
            ok,
            error,
            finally() {
                setLoading(false);
                onUpdate();
            },
        });
    };

    const actionIcon = loading
        ? ACTION_ICONS.loading
        : service.isRunning
        ? ACTION_ICONS.down
        : ACTION_ICONS.up;

    const canLaunch = !service.tags.includes(HST.cli);
    const gradientTag = service.tags.find(t => HSTColorOpts.includes(t as HST));

    const gradientClass = gradientTag ? `bg-gradient-to-tr from-0% to-50% ${HSTColors[gradientTag]}` : "";

    return (
        <div className={`p-4 rounded-box cursor-default bg-base-200/50 relative ${gradientClass}`}>
            <h2 className="flex items-center gap-1 text-2xl pb-2">
                <span className="font-bold">{service.handle}</span>

                {canLaunch && (
                    <>
                        {service.isRunning && (
                            <span className="inline-block bg-success w-2 h-2 rounded-full">
                            </span>
                        )}
                        {!service.isRunning && (
                            <span className="inline-block bg-base-content/20 w-2 h-2 rounded-full">
                            </span>
                        )}
                        <IconButton
                            disabled={loading}
                            icon={actionIcon}
                            onClick={toggleService}
                        />
                    </>
                )}

                <div className="flex-1 min-w-4"></div>
                {service.isRunning && (
                    <IconButton
                        icon={<IconExternalLink />}
                        onClick={openService}
                    />
                )}
            </h2>
            <div className="badges flex gap-2">
                {service.isDefault && (
                    <span className="badge badge-primary">
                        Default
                    </span>
                )}
                {service.tags.map(
                    (tag) => {
                        const maybeAdornment = TAG_ADORNMENTS[tag] ?? null;

                        return (
                            <span
                                key={tag}
                                className="badge bg-base-content/5 text-base-content/80"
                            >
                                {maybeAdornment}
                                {tag}
                            </span>
                        );
                    },
                )}
            </div>
        </div>
    );
};
