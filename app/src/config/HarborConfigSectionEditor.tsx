import { SECTIONS_EXTRA } from "../configMetadata";
import { useSearch } from "../useSearch";
import { useStoredState } from "../useStoredState";
import { HarborConfigSection } from "./HarborConfig";
import { HarborConfigEntryEditor } from "./HarborConfigEntryEditor";

export const HarborConfigSectionEditor = (
    { section }: { section: HarborConfigSection },
) => {
    const search = useSearch("config");
    let [open, setOpen] = useStoredState(`section:${section.name}`, false);
    const maybeExtra = SECTIONS_EXTRA[section.name];

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
            <div className="collapse collapse-arrow bg-base-200 max-w-2xl">
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
