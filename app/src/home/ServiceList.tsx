import { ChangeEvent } from "react";

import { IconRotateCW } from "../Icons";
import { Section } from "../Section";
import { ServiceCard } from "./ServiceCard";
import { Loader } from "../Loading";
import { IconButton } from "../IconButton";
import { HarborService } from "../serviceMetadata";
import { ACTION_ICONS } from "../serviceActions";
import { ServiceTag } from "../ServiceTags";
import { HST } from '../serviceMetadata';
import { runHarbor } from "../useHarbor";
import { toasted } from "../utils";
import { SearchInput } from "../SearchInput";
import { useSearch } from "../useSearch";
import { LostSquirrel } from "../LostSquirrel";
import { useState } from "react";

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

type ServiceListProps = {
  services: HarborService[];
  loading: boolean;
  error: unknown;
  rerun: () => void;
  tagFilter: string[];
  onTagFilterChange: (tags: string[]) => void;
  pinnedIds: string[];
  onTogglePin: (handle: string) => void;
  pinnedSection?: React.ReactNode;
};

export const ServiceList = ({
  services,
  loading,
  error,
  rerun,
  tagFilter,
  onTagFilterChange,
  pinnedIds,
  onTogglePin,
  pinnedSection,
}: ServiceListProps) => {
  const serviceSearch = useSearch("services");
  const [changing, setChanging] = useState(false);

  const handleTagsChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, checked } = e.target;
    const next = checked
      ? [...tagFilter, name].filter((v, i, a) => a.indexOf(v) === i)
      : tagFilter.filter((v) => v !== name);
    onTagFilterChange(next);
  };

  const handleServiceUpdate = () => {
    rerun();
  };

  const filteredServices = services.filter((service) => {
    const matchesTags =
      tagFilter.length === 0 ||
      service.tags.some((tag) => tagFilter.includes(tag));

    const matchesSearch = [
      serviceSearch.matches(service.name ?? service.handle),
      serviceSearch.matches(service.tags.join(" ")),
    ].some((match) => !!match);

    return matchesTags && matchesSearch;
  });

  const unpinnedServices = services.filter(s => !pinnedIds.includes(s.handle));
  const unpinnedFiltered = filteredServices.filter(s => !pinnedIds.includes(s.handle));
  const filtered = unpinnedServices.length - unpinnedFiltered.length;

  const orderedServices = unpinnedFiltered.sort(serviceOrderBy);
  const anyRunning = orderedServices.some((service) => service.isRunning);
  const actionIcon = changing
    ? ACTION_ICONS.loading
    : anyRunning
    ? ACTION_ICONS.down
    : ACTION_ICONS.up;
  const actionTip = anyRunning ? "Stop all services" : `Start default services`;

  const handleToggle = () => {
    const msg = (str: string) => <span>{str}</span>;

    const action = () => {
      setChanging(true);
      return runHarbor([anyRunning ? "down" : "up"]);
    };
    const ok = anyRunning
      ? msg("All services stopped")
      : msg("Started default services");
    const err = anyRunning
      ? msg("Failed to stop all services")
      : msg("Failed to start default services");

    toasted({
      action,
      ok,
      error: err,
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
          <div className="flex flex-wrap gap-1">
            {Object.values(HST).map((tag) => {
              return (
                <div className="form-control group" key={tag}>
                  <label className="label cursor-pointer p-0">
                    <input
                      className="checkbox hidden"
                      onChange={handleTagsChange}
                      type="checkbox"
                      name={tag}
                      checked={tagFilter.includes(tag)}
                      aria-label={tag}
                    />
                    <ServiceTag tag={tag} />
                  </label>
                </div>
              );
            })}
          </div>

          <span className="tooltip tooltip-bottom" data-tip={actionTip}>
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
              serviceSearch.setQuery(e.target.value)
            }
          />
        </div>
      }
      children={
        <div className="rounded-box">
          <Loader loading={loading} loader="overlay" />
          {!!error && <div className="my-2">{String((error as Error).message ?? error)}</div>}
          {pinnedSection}
          {services && (
            <ul className="flex gap-4 flex-wrap">
              {orderedServices.map((service) => (
                <li key={service.handle} className="m-0 p-0">
                  <ServiceCard
                    service={service}
                    onUpdate={handleServiceUpdate}
                    isPinned={pinnedIds.includes(service.handle)}
                    onTogglePin={onTogglePin}
                  />
                </li>
              ))}

              {filtered > 0 && !loading && (
                <li className="p-6 rounded-box cursor-default bg-base-200/50 relative flex items-center">
                  {filtered === unpinnedServices.length && (
                    <LostSquirrel className="text-base-content/40 text-2xl mr-4" />
                  )}
                  {filtered < services.length ? filtered : "Everything"}{" "}
                  filtered out
                </li>
              )}
            </ul>
          )}
        </div>
      }
    />
  );
};
