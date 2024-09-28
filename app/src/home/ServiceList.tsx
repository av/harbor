import { useState } from "react";

import { IconRotateCW } from "../Icons";
import { Section } from "../Section";
import { ServiceCard } from "./ServiceCard";
import { useServiceList } from "./useServiceList";
import { useArrayState } from "../useArrayState";
import { LinearLoader } from "../LinearLoading";
import { IconButton } from "../IconButton";
import { HST } from "../serviceMetadata";

export const ServiceList = () => {
    const { services, loading, error, rerun } = useServiceList();
    const { toggle, items } = useArrayState(useState<string[]>([]));

    const handleTagsChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const { name, checked } = e.target;
        toggle(name, checked);
    }

    const filteredServices = services?.filter((service) => {
        if (!items.length) {
            return true;
        }

        return service.tags.some((tag) => {
            return items.includes(tag);
        });
    });

    return (
        <Section
            header={
                <div className="flex flex-wrap gap-2 items-center">
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
                    <IconButton icon={<IconRotateCW />} onClick={rerun} />
                </div>
            }
            children={
                <>
                    <LinearLoader loading={loading} />
                    {error && <div className="my-2">{error.message}</div>}
                    {services && (
                        <ul className="flex gap-2 flex-wrap">
                            {filteredServices.map((service) => {
                                return (
                                    <li
                                        key={service.handle}
                                        className="m-0 p-0"
                                    >
                                        <ServiceCard service={service} />
                                    </li>
                                );
                            })}
                        </ul>
                    )}
                </>
            }
        />
    );
};
