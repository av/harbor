import { HarborService } from "../serviceMetadata";

export function matchesServiceFilter(
    service: HarborService,
    searchMatches: (str: string) => boolean,
    tagFilter: string[],
): boolean {
    const matchesTags =
        tagFilter.length === 0 ||
        service.tags.some((tag) => tagFilter.includes(tag));

    const matchesSearch =
        searchMatches(service.name ?? service.handle) ||
        searchMatches(service.tags.join(" "));

    return matchesTags && matchesSearch;
}
