import { ChangeEvent, useState } from "react";

import { IconRotateCW } from "../Icons";
import { Section } from "../Section";
import { ServiceCard } from "./ServiceCard";
import { useServiceList } from "./useServiceList";
import { useArrayState } from "../useArrayState";
import { Loader } from "../Loading";
import { IconButton } from "../IconButton";
import { ACTION_ICONS, HarborService, HST } from "../serviceMetadata";
import { runHarbor } from "../useHarbor";
import { toasted } from "../utils";
import { SearchInput } from "../SearchInput";
import { useSearch } from "../useSearch";
import { LostSquirrel } from "../LostSquirrel";

const serviceOrderBy = (a: HarborService, b: HarborService) => {
    if ((a.isRunning || a.isDefault) && !(b.isRunning || b.isDefault)) {
        return -1;
    }
    if (!(a.isRunning || a.isDefault) && (b.isRunning || b.isDefault)) {
        return 1;
    }

    return a.handle.localeCompare(b.handle, undefined, {
        numeric: true,
        sensitivity: "base",
    });
};

export const ServiceList = () => {
    const serviceSearch = useSearch("services");
    const { services, loading, error, rerun } = useServiceList();
    const { toggle, items } = useArrayState(useState<string[]>([]));
    const [changing, setChanging] = useState(false);

    const handleTagsChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const { name, checked } = e.target;
        toggle(name, checked);
    };

    const handleServiceUpdate = () => {
        rerun();
    };

    const filteredServices = services?.filter((service) => {
        const matchesTags = items.length === 0 || service.tags.some((tag) => {
            return items.includes(tag);
        });

        const matchesSearch = [
            serviceSearch.matches(service.handle),
            serviceSearch.matches(service.tags.join(" ")),
        ].some((match) => !!match);

        return matchesTags && matchesSearch;
    });

    const filtered = services.length - filteredServices.length;

    const orderedServices = filteredServices?.sort(serviceOrderBy);
    const anyRunning = orderedServices?.some((service) => service.isRunning);
    const actionIcon = changing
        ? ACTION_ICONS.loading
        : anyRunning
        ? ACTION_ICONS.down
        : ACTION_ICONS.up;
    const actionTip = anyRunning
        ? "Stop all services"
        : `Start default services`;

    const handleToggle = () => {
        const msg = (str: string) => <span>{str}</span>;

        const action = () => {
            setChanging(true);
            return runHarbor([
                anyRunning ? "down" : "up",
            ]);
        };
        const ok = anyRunning
            ? msg("All services stopped")
            : msg("Started default services");
        const error = anyRunning
            ? msg("Failed to stop all services")
            : msg("Failed to start default services");

        toasted({
            action,
            ok,
            error,
            finally() {
                setChanging(false);
                handleServiceUpdate();
            },
        });
    };

    return (
        <Section
            header={
                <div className="flex flex-wrap gap-4 items-center mb-4">
                    <span>Services</span>
                    <div className="join flex-wrap">
                        {Object.values(HST).map((tag) => {
                            return (
                                <input
                                    key={tag}
                                    onChange={handleTagsChange}
                                    className="join-item btn btn-sm"
                                    type="checkbox"
                                    name={tag}
                                    aria-label={tag}
                                />
                            );
                        })}
                    </div>

                    <span
                        className="tooltip tooltip-bottom"
                        data-tip={actionTip}
                    >
                        <IconButton
                            icon={actionIcon}
                            onClick={handleToggle}
                            disabled={changing}
                        />
                    </span>

                    <span className="tooltip tooltip-bottom" data-tip="Refresh">
                        <IconButton icon={<IconRotateCW />} onClick={rerun} />
                    </span>

                    <SearchInput
                        defaultValue={serviceSearch.query}
                        onChange={(e: ChangeEvent<HTMLInputElement>) =>
                            serviceSearch.setQuery(e.target.value)}
                    />
                </div>
            }
            children={
                <div className="relative rounded-box">
                    <Loader loading={loading} loader="overlay" />
                    {error && <div className="my-2">{error.message}</div>}
                    {services && (
                        <ul className="flex gap-4 flex-wrap">
                            {orderedServices.map((service) => {
                                return (
                                    <li
                                        key={service.handle}
                                        className="m-0 p-0"
                                    >
                                        <ServiceCard
                                            service={service}
                                            onUpdate={handleServiceUpdate}
                                        />
                                    </li>
                                );
                            })}

                            {filtered > 0 && !loading && (
                                <li className="p-6 rounded-box cursor-default bg-base-200/50 relative flex items-center">
                                    {filtered === services.length && <LostSquirrel className="text-base-content/40 text-2xl mr-4" />}
                                    {filtered < services.length
                                        ? filtered
                                        : "Everything"} filtered out
                                </li>
                            )}
                        </ul>
                    )}
                </div>
            }
        />
    );
};
