import { useEffect, useState } from 'react';
import { ScrollToTop } from '../ScrollToTop';
import { ServiceList } from "./ServiceList";
import { PinnedServices } from "./PinnedServices";
import { useServiceList } from "./useServiceList";
import { useStoredState } from "../useStoredState";
import { useSearch } from "../useSearch";

export const Home = () => {
  const { services, loading, error, rerun } = useServiceList();
  const [tagFilter, setTagFilter] = useState<string[]>([]);
  const [pinnedIds, setPinnedIds] = useStoredState<string[]>("pinnedServices", []);
  const serviceSearch = useSearch("services");

  // Clean up stale pins when service handles change
  useEffect(() => {
    if (services.length === 0) return;
    const handles = new Set(services.map((s) => s.handle));
    const cleaned = pinnedIds.filter((id) => handles.has(id));
    if (cleaned.length !== pinnedIds.length) {
      setPinnedIds(cleaned);
    }
  }, [services]);

  const handleTogglePin = (handle: string) => {
    if (pinnedIds.includes(handle)) {
      setPinnedIds(pinnedIds.filter((id) => id !== handle));
    } else {
      setPinnedIds([...pinnedIds, handle]);
    }
  };

  return (
    <>
      <ServiceList
        services={services}
        loading={loading}
        error={error}
        rerun={rerun}
        tagFilter={tagFilter}
        onTagFilterChange={setTagFilter}
        pinnedIds={pinnedIds}
        onTogglePin={handleTogglePin}
        pinnedSection={
          <PinnedServices
            services={services}
            pinnedIds={pinnedIds}
            searchQuery={serviceSearch.query}
            tagFilter={tagFilter}
            onUpdate={rerun}
            onTogglePin={handleTogglePin}
          />
        }
      />
      <ScrollToTop />
    </>
  );
};
