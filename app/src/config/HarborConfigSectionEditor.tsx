import { SECTIONS_EXTRA } from "../configMetadata";
import { useSearch } from "../useSearch";
import { useStoredState } from "../useStoredState";
import { HarborConfigSection } from "./HarborConfig";
import { HarborConfigEntryEditor } from "./HarborConfigEntryEditor";
import { useSharedState } from "../useSharedState";
import { useLayoutEffect, useRef } from "react";
import { normalizeServiceKey } from "../utils";

export const HarborConfigSectionEditor = (
    { section }: { section: HarborConfigSection },
) => {
    const search = useSearch("config");
    let [open, setOpen] = useStoredState(`section:${section.name}`, false);
    const maybeExtra = SECTIONS_EXTRA[section.name];
    const [configDeepLink, setConfigDeepLink] = useSharedState<string | null>("configDeepLink", null);
    const sectionRef = useRef<HTMLDivElement>(null);
    const scrollFiredRef = useRef(false);

    const isDeepLinked = configDeepLink !== null &&
        normalizeServiceKey(configDeepLink) === normalizeServiceKey(section.name);

    // Force-expand and scroll if this section matches the deep link.
    // useLayoutEffect ensures this runs synchronously after every render,
    // so it fires as soon as the section mounts with a matching configDeepLink.
    useLayoutEffect(() => {
        if (isDeepLinked && !scrollFiredRef.current) {
            scrollFiredRef.current = true;
            setOpen(true);
            setConfigDeepLink(null);

            setTimeout(() => {
                sectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
            }, 100);
        }
    }, [isDeepLinked]);

    const filteredEntries = section.entries.filter((entry) => {
        return search.matches(entry.id);
    });

    // Keep sections open when searching
    if (!!search.query) {
        open = true;
    }

    if (filteredEntries.length === 0) {
        return null;
    }

    const filtered = section.entries.length - filteredEntries.length;

    return (
        <>
            <div ref={sectionRef} className="collapse collapse-arrow bg-base-200 max-w-2xl">
                <input
                    type="checkbox"
                    checked={open}
                    onChange={(e) => setOpen(e.target.checked)}
                />
                <div className="collapse-title flex flex-col">
                    <h2 className="text-xl font-bold">{section.name}</h2>

                    {maybeExtra && (
                        <p>
                            {maybeExtra.content}
                        </p>
                    )}
                </div>
                <div className="collapse-content flex flex-col gap-4 rounded-box">
                    {filteredEntries.map((entry) => {
                        return (
                            <HarborConfigEntryEditor
                                key={entry.id}
                                entry={entry}
                            />
                        );
                    })}

                    {filtered > 0 && (
                        <div className="text-sm text-base-content/40">
                            {filtered} more filtered out
                        </div>
                    )}
                </div>
            </div>
        </>
    );
};
