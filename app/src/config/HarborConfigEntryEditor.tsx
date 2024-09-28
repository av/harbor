import { HarborConfigEntry } from "./HarborConfig";

export const HarborConfigEntryEditor = ({ entry }: { entry: HarborConfigEntry }) => {
    const config = entry.config?.use();

    return (
        <div className="flex flex-col gap-1">
            <span className="capitalize text">{entry.name}</span>
            <input
                type="text"
                className="input input-md w-full max-w-2xl"
                disabled={config?.isReadonly}
                value={entry.value}
                onChange={(e) => {
                    console.log('===============');
                    console.log(config);
                    console.log('===============');
                    config?.setValue(entry.id, e.target.value);
                }}
            />
        </div>
    );
}