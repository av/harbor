import { IconCheck, IconOctagonAlert, IconStop, IconX } from "../Icons";
import { XTermView } from "../terminal/XTermView";
import { type ModelPullSession } from "./ModelPullContext";

interface ModelPullPaneProps {
    session: ModelPullSession;
    onCancel: () => void;
    onDismiss: () => void;
}

const STATUS_META: Record<string, { badgeClass: string; label: string }> = {
    running:   { badgeClass: "badge-info",    label: "Running" },
    success:   { badgeClass: "badge-success", label: "Success" },
    failure:   { badgeClass: "badge-error",   label: "Failed" },
    cancelled: { badgeClass: "badge-warning", label: "Cancelled" },
};

const DEFAULT_STATUS_META = { badgeClass: "badge-ghost", label: "Pending" };

function getStatusMeta(status: ModelPullSession["status"]) {
    return STATUS_META[status] ?? DEFAULT_STATUS_META;
}

export const ModelPullPane = ({ session, onCancel, onDismiss }: ModelPullPaneProps) => {
    const statusMeta = getStatusMeta(session.status);
    const hasOutput = session.chunks.length > 0;

    return (
        <div className="border border-base-content/10 rounded-box overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-2 bg-base-200 border-b border-base-content/10">
                <span className="text-sm font-medium flex-1 min-w-0 truncate" title={session.modelName}>
                    {session.modelName} — Pull
                </span>
                {session.status === "running" ? (
                    <span className="loading loading-spinner loading-xs text-base-content/50" />
                ) : session.status === "success" ? (
                    <IconCheck className="w-4 h-4 text-success" />
                ) : session.status === "failure" ? (
                    <IconOctagonAlert className="w-4 h-4 text-error" />
                ) : session.status === "cancelled" ? (
                    <IconX className="w-4 h-4 text-warning" />
                ) : null}
                <span className={`badge badge-sm ${statusMeta.badgeClass}`}>
                    {statusMeta.label}
                </span>
                {session.canCancel ? (
                    <button
                        type="button"
                        className="btn btn-xs btn-ghost gap-1"
                        onClick={onCancel}
                    >
                        <IconStop className="w-3.5 h-3.5" />
                        Cancel
                    </button>
                ) : (
                    <button
                        type="button"
                        className="btn btn-xs btn-ghost gap-1"
                        onClick={onDismiss}
                    >
                        <IconX className="w-3.5 h-3.5" />
                        Dismiss
                    </button>
                )}
            </div>

            <div className="px-3 py-2 bg-base-200 border-b border-base-content/10">
                <code className="text-xs break-all text-base-content/60">
                    harbor {session.command.join(" ")}
                </code>
            </div>

            <div
                className="relative bg-base-200"
                style={{ resize: "vertical", overflow: "hidden", minHeight: "150px" }}
            >
                <XTermView
                    chunks={session.chunks}
                    bufferVersion={session.bufferVersion}
                    height="100%"
                />
                {!hasOutput && (
                    <div className="absolute inset-0 flex items-center px-3 py-4 pointer-events-none">
                        {session.status === "running" ? (
                            <div className="flex items-center gap-2 text-base-content/50 text-sm">
                                <span className="loading loading-spinner loading-xs" />
                                Starting model pull...
                            </div>
                        ) : (
                            <p className="text-base-content/40 text-sm">
                                No pull output captured.
                            </p>
                        )}
                    </div>
                )}
            </div>

            {session.error && (
                <div className="bg-base-200 p-3 border-t border-base-content/10">
                    <div className="alert alert-error text-sm">
                        <span>{session.error}</span>
                    </div>
                </div>
            )}
        </div>
    );
};
