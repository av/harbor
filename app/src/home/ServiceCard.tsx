import { IconButton } from "../IconButton";
import {
    IconAudioLines,
    IconAward,
    IconBandage,
    IconExternalLink,
} from "../Icons";
import { HarborService, HST } from "../serviceMetadata";
import { runHarbor } from "../useHarbor";

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

export const ServiceCard = ({ service }: { service: HarborService }) => {
    const openService = () => {
        runHarbor(["open", service.handle]);
    };

    return (
        <div className="p-4 rounded-box cursor-default bg-base-300/20">
            <h2 className="flex items-center gap-1 text-2xl pb-2">
                <span className="font-bold">{service.handle}</span>
                {service.isRunning && (
                    <span className="inline-block bg-success w-2 h-2 rounded-full">
                    </span>
                )}
                <div className="flex-1"></div>
                {service.isRunning && (
                    <IconButton icon={<IconExternalLink />} onClick={openService} />
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
                                className="badge bg-base-content/5"
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
