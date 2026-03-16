import { useState, useRef, useMemo, useEffect } from "react";
import { runHarbor } from "../useHarbor";
import { useOverlays } from "../OverlayContext";
import { ConfirmModal } from "../ConfirmModal";
import { Loader } from "../Loading";
import { IconTrash, IconRotateCW, IconArrowUpDown, IconArrowDownToLine, IconBrandOllama, IconBrandHuggingFace, IconCopy, IconCheck } from "../Icons";
import { runOpen } from "../useOpen";
import { IconButton } from "../IconButton";
import { Section } from "../Section";
import { useModels } from "./useModels";
import { ModelEntry, formatSize, formatDate, detailSummary } from "./ModelEntry";
import { LostSquirrel } from "../LostSquirrel";
import { useModelPull } from "./ModelPullContext";
import { ModelPullPane } from "./ModelPullPane";

type SortField = "model" | "size" | "modified";
type SortDir = "asc" | "desc";

const SOURCE_BADGE: Record<string, string> = {
    ollama: "badge-primary",
    hf: "badge-secondary",
    llamacpp: "badge-accent",
};

function sourceBadgeClass(source: string): string {
    return SOURCE_BADGE[source] ?? "badge-ghost";
}

export const Models = () => {
    const { models, status, error, reload } = useModels();
    const { session: pullSession, startPull, cancelPull, dismissSession } = useModelPull();
    const overlays = useOverlays();

    const [sourceFilter, setSourceFilter] = useState<string | null>(null);
    const [nameFilter, setNameFilter] = useState("");
    const [sortField, setSortField] = useState<SortField>("modified");
    const [sortDir, setSortDir] = useState<SortDir>("desc");
    const [pullInput, setPullInput] = useState("");
    const [removingModel, setRemovingModel] = useState<string | null>(null);
    const [copiedModel, setCopiedModel] = useState<string | null>(null);

    const pullInputRef = useRef<HTMLInputElement>(null);
    const nameFilterRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        const handler = (e: KeyboardEvent) => {
            if ((e.ctrlKey || e.metaKey) && e.key === "f") {
                e.preventDefault();
                nameFilterRef.current?.focus();
            }
        };
        window.addEventListener("keydown", handler);
        return () => window.removeEventListener("keydown", handler);
    }, []);

    const sources = useMemo(
        () => Array.from(new Set(models.map((m) => m.source))).sort(),
        [models],
    );

    const filtered = useMemo(() => {
        let list = sourceFilter ? models.filter((m) => m.source === sourceFilter) : models;
        if (nameFilter.trim()) {
            const q = nameFilter.trim().toLowerCase();
            list = list.filter((m) => m.model.toLowerCase().includes(q));
        }
        return [...list].sort((a, b) => {
            let cmp = 0;
            if (sortField === "model") cmp = a.model.localeCompare(b.model);
            else if (sortField === "size") cmp = a.size - b.size;
            else cmp = new Date(a.modified).getTime() - new Date(b.modified).getTime();
            return sortDir === "asc" ? cmp : -cmp;
        });
    }, [models, sourceFilter, nameFilter, sortField, sortDir]);

    const handleSort = (field: SortField) => {
        if (sortField === field) {
            setSortDir((d) => (d === "asc" ? "desc" : "asc"));
        } else {
            setSortField(field);
            setSortDir("asc");
        }
    };

    const SortIndicator = ({ field }: { field: SortField }) => {
        if (sortField !== field) return <IconArrowUpDown className="opacity-30 text-sm" />;
        return <span className="text-xs">{sortDir === "asc" ? "↑" : "↓"}</span>;
    };

    const handlePull = () => {
        const name = pullInput.trim();
        if (!name) return;
        setPullInput("");
        startPull(name);
    };

    const handleRemove = (entry: ModelEntry) => {
        overlays.open(
            <ConfirmModal
                key="confirm-remove-model"
                onConfirm={async () => {
                    setRemovingModel(entry.model);
                    try {
                        await runHarbor(["models", "rm", entry.model]);
                        reload();
                    } finally {
                        setRemovingModel(null);
                    }
                }}
            >
                <h2 className="text-2xl mb-2 font-bold">Remove model?</h2>
                <p className="break-all">
                    <span className="font-mono">{entry.model}</span> will be permanently deleted from{" "}
                    <span className="font-semibold">{entry.source}</span> cache.
                </p>
                <p className="mt-1">Are you sure?</p>
            </ConfirmModal>,
        );
    };

    const isPulling = pullSession?.isActive ?? false;

    return (
        <div className="flex flex-col gap-4 max-w-4xl">
            <Section
                header={
                    <>
                        <span>Models</span>
                        <IconButton
                            icon={<IconRotateCW />}
                            onClick={reload}
                            disabled={status === "loading"}
                            title="Refresh"
                        />
                        <IconButton
                            icon={<span className="text-[1.25em]"><IconBrandOllama /></span>}
                            onClick={() => runOpen(["https://ollama.com/search"])}
                            title="Browse Ollama models"
                        />
                        <IconButton
                            icon={<span className="text-[1.25em]"><IconBrandHuggingFace /></span>}
                            onClick={() => runOpen(["https://huggingface.co/models?library=gguf"])}
                            title="Browse HuggingFace models"
                        />
                    </>
                }
            >
            {/* Pull input */}
            <div className="rounded-box bg-base-200 p-4 flex flex-col gap-3">
                <span className="font-semibold">Pull a model</span>
                <form
                    className="flex gap-2"
                    onSubmit={(e) => {
                        e.preventDefault();
                        handlePull();
                    }}
                >
                    <input
                        ref={pullInputRef}
                        className="input input-bordered flex-1"
                        placeholder="e.g. llama3.2:3b or unsloth/Qwen3-4B-Instruct-GGUF"
                        value={pullInput}
                        onChange={(e) => setPullInput(e.target.value)}
                        disabled={isPulling}
                    />
                    <button
                        type="submit"
                        className="btn btn-sm btn-primary"
                        disabled={isPulling || !pullInput.trim()}
                    >
                        <IconArrowDownToLine className="w-4 h-4" />
                        {isPulling ? "Pulling…" : "Pull"}
                    </button>
                </form>
                <p className="text-xs text-base-content/50">
                    Accepts Ollama model IDs (e.g. <span className="font-mono">llama3.2:3b</span>, <span className="font-mono">qwen3.5:9b</span>) or HuggingFace repo IDs (e.g. <span className="font-mono">unsloth/Qwen3-4B-Instruct-GGUF</span>).
                </p>
                {pullSession && (
                    <ModelPullPane
                        session={pullSession}
                        onCancel={cancelPull}
                        onDismiss={dismissSession}
                    />
                )}
            </div>

            {/* Source filter chips + name filter */}
            <div className="flex flex-wrap items-center gap-2 mt-2">
                {sources.length > 1 && (
                    <>
                        <button
                            className={`btn btn-xs ${sourceFilter === null ? "btn-primary" : "btn-ghost"}`}
                            onClick={() => setSourceFilter(null)}
                        >
                            All
                        </button>
                        {sources.map((src) => (
                            <button
                                key={src}
                                className={`btn btn-xs ${sourceFilter === src ? "btn-primary" : "btn-ghost"}`}
                                onClick={() => setSourceFilter(src === sourceFilter ? null : src)}
                            >
                                {src}
                            </button>
                        ))}
                        <div className="divider divider-horizontal mx-0 h-5 self-center" />
                    </>
                )}
                <input
                    ref={nameFilterRef}
                    type="text"
                    className="input input-bordered input-sm"
                    placeholder="Filter models… (Ctrl+F)"
                    value={nameFilter}
                    onChange={(e) => setNameFilter(e.target.value)}
                />
                {status === "ok" && (
                    <span className="text-sm text-base-content/50">
                        {filtered.length} {filtered.length === 1 ? "model" : "models"}
                    </span>
                )}
            </div>

            {/* States */}
            <Loader loading={status === "loading"} />

            {status === "error" && (
                <div className="alert alert-error flex items-center gap-3">
                    <span className="flex-1">{error}</span>
                    <button className="btn btn-sm btn-outline" onClick={reload}>
                        <IconRotateCW className="w-4 h-4" /> Retry
                    </button>
                </div>
            )}

            {status === "ok" && filtered.length === 0 && (
                <div className="rounded-box bg-base-200 p-6 flex items-center gap-4 text-base-content/60">
                    <LostSquirrel className="text-4xl" />
                    <span>No models found. Pull a model to get started.</span>
                </div>
            )}

            {/* Table */}
            {status === "ok" && filtered.length > 0 && (
                <div className="overflow-x-auto rounded-box">
                    <table className="table table-zebra w-full">
                        <thead>
                            <tr>
                                <th className="w-24">Source</th>
                                <th>
                                    <button
                                        className="flex items-center gap-1"
                                        onClick={() => handleSort("model")}
                                    >
                                        Model <SortIndicator field="model" />
                                    </button>
                                </th>
                                <th>Details</th>
                                <th>
                                    <button
                                        className="flex items-center gap-1"
                                        onClick={() => handleSort("size")}
                                    >
                                        Size <SortIndicator field="size" />
                                    </button>
                                </th>
                                <th>
                                    <button
                                        className="flex items-center gap-1"
                                        onClick={() => handleSort("modified")}
                                    >
                                        Modified <SortIndicator field="modified" />
                                    </button>
                                </th>
                                <th></th>
                            </tr>
                        </thead>
                        <tbody>
                            {filtered.map((entry) => {
                                const isRemoving = removingModel === entry.model;
                                return (
                                    <tr key={`${entry.source}::${entry.model}`} className={`group ${isRemoving ? "opacity-50" : ""}`}>
                                        <td>
                                            <span className={`badge badge-sm font-mono ${sourceBadgeClass(entry.source)}`}>
                                                {entry.source}
                                            </span>
                                        </td>
                                        <td className="max-w-xs">
                                            <div className="flex items-center gap-1 max-w-xs">
                                                <span
                                                    className="font-mono text-sm truncate"
                                                    title={entry.model}
                                                >
                                                    {entry.model}
                                                </span>
                                                <button
                                                    className="opacity-0 group-hover:opacity-100 transition-opacity btn btn-ghost btn-xs btn-circle shrink-0"
                                                    title="Copy model ID"
                                                    onClick={() => {
                                                        navigator.clipboard.writeText(entry.model);
                                                        setCopiedModel(entry.model);
                                                        setTimeout(() => setCopiedModel(null), 1500);
                                                    }}
                                                >
                                                    {copiedModel === entry.model
                                                        ? <IconCheck className="w-3 h-3 text-success" />
                                                        : <IconCopy className="w-3 h-3" />
                                                    }
                                                </button>
                                            </div>
                                        </td>
                                        <td className="text-sm text-base-content/60">{detailSummary(entry)}</td>
                                        <td className="text-sm tabular-nums whitespace-nowrap">{formatSize(entry.size)}</td>
                                        <td className="text-sm text-base-content/60 whitespace-nowrap">{formatDate(entry.modified)}</td>
                                        <td>
                                            <IconButton
                                                icon={<IconTrash />}
                                                className="opacity-0 group-hover:opacity-100 transition-opacity"
                                                onClick={() => handleRemove(entry)}
                                                disabled={isRemoving}
                                                title="Remove model"
                                            />
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            )}
            </Section>
        </div>
    );
};
