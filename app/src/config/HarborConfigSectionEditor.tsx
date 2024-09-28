import { SECTIONS_EXTRA } from "../configMetadata";
import { useStoredState } from "../useStoredState";
import { HarborConfigSection } from "./HarborConfig";
import { HarborConfigEntryEditor } from "./HarborConfigEntryEditor";

export const HarborConfigSectionEditor = (
    { section }: { section: HarborConfigSection },
) => {
    const [open, setOpen] = useStoredState(`section:${section.name}`, false);
    const maybeExtra = SECTIONS_EXTRA[section.name];

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
                    {section.entries.map((entry) => {
                        return (
                            <HarborConfigEntryEditor
                                key={entry.id}
                                entry={entry}
                            />
                        );
                    })}
                </div>
            </div>
        </>
    );
};
