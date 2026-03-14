export interface ModelDetails {
    family?: string;
    parameters?: string;
    quantization?: string;
}

export interface ModelEntry {
    source: string;
    model: string;
    size: number;
    modified: string;
    details?: ModelDetails;
    files?: string[];
}

export function parseModels(json: string): ModelEntry[] {
    const raw = JSON.parse(json);
    if (!Array.isArray(raw)) return [];
    return raw as ModelEntry[];
}

export function formatSize(bytes: number): string {
    if (bytes >= 1e12) return `${(bytes / 1e12).toFixed(1)} TB`;
    if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
    if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(0)} MB`;
    if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(0)} KB`;
    return `${bytes} B`;
}

export function formatDate(iso: string): string {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function detailSummary(entry: ModelEntry): string {
    const { details } = entry;
    if (!details) return "";
    const parts: string[] = [];
    if (details.family) parts.push(details.family);
    if (details.parameters) parts.push(details.parameters);
    if (details.quantization) parts.push(details.quantization);
    return parts.join(" · ");
}
