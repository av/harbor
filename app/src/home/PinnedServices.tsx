import { HarborService } from "../serviceMetadata";
import { ServiceCard } from "./ServiceCard";
import { matchesServiceFilter } from "./serviceFilter";

type PinnedServicesProps = {
  services: HarborService[];
  pinnedIds: string[];
  searchMatches: (str: string) => boolean;
  tagFilter: string[];
  onUpdate: () => void;
  onTogglePin: (handle: string) => void;
};

export const PinnedServices = ({
  services,
  pinnedIds,
  searchMatches,
  tagFilter,
  onUpdate,
  onTogglePin,
}: PinnedServicesProps) => {
  if (pinnedIds.length === 0) {
    return null;
  }

  const pinnedServices = services
    .filter((s) => pinnedIds.includes(s.handle))
    .filter((s) => matchesServiceFilter(s, searchMatches, tagFilter))
    .sort((a, b) =>
      (a.name ?? a.handle).localeCompare(b.name ?? b.handle, undefined, {
        numeric: true,
        sensitivity: "base",
      })
    );

  if (pinnedServices.length === 0) {
    return null;
  }

  return (
    <div className="mb-2">
      <span className="text-xs text-base-content/40 uppercase tracking-widest">Pinned</span>
      <ul className="flex gap-4 flex-wrap mt-2">
        {pinnedServices.map((service) => (
          <li key={service.handle} className="m-0 p-0">
            <ServiceCard
              service={service}
              onUpdate={onUpdate}
              isPinned={true}
              onTogglePin={onTogglePin}
            />
          </li>
        ))}
      </ul>
      <div className="border-t border-base-content/10 my-6" />
    </div>
  );
};
