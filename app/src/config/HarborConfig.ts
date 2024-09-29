import { remove, writeTextFile } from "@tauri-apps/plugin-fs";
import { join } from "@tauri-apps/api/path";

import {
    CURRENT_PROFILE,
    DEFAULT_PROFILE,
    HARBOR_PREFIX,
    HarborProfile,
} from "../configMetadata";
import { DataClass } from "../DataClass";
import { resolveProfilesDir, runHarbor } from "../useHarbor";

export class HarborConfigEntry {
    id: string;
    name: string;
    value: string;
    sectionId: string;
    section: HarborConfigSection | null = null;
    config: HarborConfig | null = null;

    static isQuotable(value: string) {
        return value.includes(" ") || value.includes("=") || value === "";
    }

    static fromString(line: string): HarborConfigEntry {
        let [id, ...eqRest] = line.split("=");
        let value = eqRest.join("=");

        const [sectionId, ...rest] = id.replace(HARBOR_PREFIX, "").split("_");
        const name = rest.join(" ").toLocaleLowerCase();

        if (value.startsWith('"') && value.endsWith('"')) {
            value = value.slice(1, -1);
        }

        return new HarborConfigEntry({
            id,
            name,
            sectionId,
            value,
        });
    }

    constructor({
        id,
        name,
        value,
        sectionId,
        section,
        config,
    }: {
        id: string;
        name: string;
        value: string;
        sectionId: string;
        section?: HarborConfigSection;
        config?: HarborConfig;
    }) {
        this.id = id;
        this.name = name;
        this.value = value;
        this.sectionId = sectionId;
        this.section = section || null;
        this.config = config || null;
    }

    toString() {
        let value = this.value;

        if (HarborConfigEntry.isQuotable(value)) {
            value = `"${value}"`;
        }

        return `${this.id}=${value}`;
    }
}

export type HarborConfigSection = {
    name: string;
    entries: HarborConfigEntry[];
    config: HarborConfig;
};

export class HarborConfig extends DataClass {
    static cache = new Map<string, HarborConfig>();
    static cached(profile: HarborProfile) {
        if (!HarborConfig.cache.has(profile.name)) {
            HarborConfig.cache.set(profile.name, new HarborConfig(profile));
        }

        return HarborConfig.cache.get(profile.name)!;
    }

    profile: HarborProfile;
    isDefault: boolean = false;
    isReadonly: boolean = false;
    isCurrent: boolean = false;
    sections: HarborConfigSection[] = [];
    entries: Record<string, HarborConfigEntry> = {};

    getMutableFields(): string[] {
        return ["setValue", "save"];
    }

    constructor(profile: HarborProfile) {
        super();

        this.profile = profile;
        this.isDefault = profile.name === DEFAULT_PROFILE;
        this.isCurrent = profile.name === CURRENT_PROFILE;
        this.isReadonly = this.isDefault;
        this.rollback();
    }

    rollback() {
        const sections: Record<string, HarborConfigSection> = {};
        const entries: Record<string, HarborConfigEntry> = {};

        const lines = this.profile.content.split("\n");

        for (const line of lines) {
            if (line.startsWith(HARBOR_PREFIX)) {
                const entry = HarborConfigEntry.fromString(line);
                let section = sections[entry.sectionId] || {
                    name: entry.sectionId,
                    entries: [],
                    config: this,
                };

                if (!sections[entry.sectionId]) {
                    sections[entry.sectionId] = section;
                }

                entries[entry.id] = entry;
                section.entries.push(entry);
                entry.section = section;
                entry.config = this;
            }
        }

        this.sections = Object.values(sections);
        this.entries = entries;
    }

    commit() {
        const lines = this.profile.content.split("\n");

        const updated = lines.map((line) => {
            if (line.startsWith(HARBOR_PREFIX)) {
                const entry = HarborConfigEntry.fromString(line);
                const updated = this.entries[entry.id];

                if (updated) {
                    return updated.toString();
                }
            }

            return line;
        });

        this.profile.content = updated.join("\n");
    }

    setValue(id: string, value: string) {
        const entry = this.entries[id];

        if (entry) {
            entry.value = value;
        }
    }

    async save() {
        this.commit();
        await writeTextFile(this.profile.file, this.profile.content);
    }

    async saveAs(name: string) {
        const profilesDir = await resolveProfilesDir();
        const newProfile: HarborProfile = {
            name,
            file: await join(profilesDir, `${name}.env`),
            content: this.profile.content,
        };

        const newConfig = new HarborConfig(newProfile);
        await newConfig.save();
    }

    async apply() {
        this.save();
        await runHarbor(["profile", "use", this.profile.name]);
    }

    async reset() {
        const defaultConfig = HarborConfig.cache.get(DEFAULT_PROFILE);

        if (!defaultConfig) {
            throw new Error("Unable to reset: default config not found");
        }

        this.profile.content = defaultConfig.profile.content;
        this.rollback();
        this.save();
    }

    async delete() {
        await remove(this.profile.file);
    }
}
