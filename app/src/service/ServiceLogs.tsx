import { useEffect, useReducer, useRef } from "react";
import { HarborService } from "../serviceMetadata";
import { useHarborStream } from "./useHarborStream";
import { IconArrowDownToLine, IconEraser, IconX } from "../Icons";

interface ServiceLogsProps {
    service: HarborService;
    onClose: () => void;
}

export const ServiceLogs = ({ service, onClose }: ServiceLogsProps) => {
    const { lines, isStreaming, error, start, stop, clear } = useHarborStream([
        "logs",
        service.handle,
    ]);

    const scrollRef = useRef<HTMLDivElement>(null);
    // true = user has scrolled away from bottom; do not auto-scroll
    const userScrolled = useRef(false);
    const showScrollBtn = useRef(false);
    // Force re-render when showScrollBtn changes
    const [, forceUpdate] = useReducer((n: number) => n + 1, 0);

    useEffect(() => {
        start();
        return () => {
            stop();
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => {
        const el = scrollRef.current;
        if (!el) return;

        if (!userScrolled.current) {
            el.scrollTo({ top: el.scrollHeight });
        }
    }, [lines]);

    const handleScroll = () => {
        const el = scrollRef.current;
        if (!el) return;

        const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 8;
        const wasShowingBtn = showScrollBtn.current;

        userScrolled.current = !atBottom;
        showScrollBtn.current = !atBottom;

        if (wasShowingBtn !== showScrollBtn.current) {
            forceUpdate();
        }
    };

    const scrollToBottom = () => {
        const el = scrollRef.current;
        if (!el) return;
        el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
        userScrolled.current = false;
        showScrollBtn.current = false;
        forceUpdate();
    };

    const handleClose = () => {
        stop();
        onClose();
    };

    const renderBody = () => {
        if (error) {
            return (
                <div className="alert alert-error text-sm">
                    <span>{error}</span>
                </div>
            );
        }

        if (lines.length === 0 && isStreaming) {
            return (
                <div className="flex items-center gap-2 text-base-content/50 text-sm py-4 px-1">
                    <span className="loading loading-spinner loading-xs" />
                    Connecting to log stream...
                </div>
            );
        }

        if (lines.length === 0 && !isStreaming) {
            return (
                <p className="text-base-content/40 text-sm py-4 px-1">
                    No log output yet.
                </p>
            );
        }

        return lines.map((line, i) => (
            <div
                key={i}
                className={`whitespace-pre-wrap break-words leading-snug ${
                    line === "(older lines trimmed)"
                        ? "text-base-content/40 italic"
                        : ""
                }`}
                dangerouslySetInnerHTML={{ __html: line }}
            />
        ));
    };

    return (
        <div className="border border-base-content/10 rounded-box overflow-hidden">
            {/* Header */}
            <div className="flex items-center gap-2 px-3 py-2 bg-base-200 border-b border-base-content/10">
                <span className="text-sm font-medium flex-1">
                    {service.name ?? service.handle} — Logs
                </span>
                {isStreaming && (
                    <span className="loading loading-spinner loading-xs text-base-content/50" />
                )}
                <button
                    type="button"
                    className="btn btn-xs btn-ghost gap-1"
                    title="Clear"
                    onClick={clear}
                >
                    <IconEraser className="w-3.5 h-3.5" />
                    Clear
                </button>
                <button
                    type="button"
                    className="btn btn-xs btn-ghost btn-circle"
                    title="Close"
                    onClick={handleClose}
                >
                    <IconX className="w-3.5 h-3.5" />
                </button>
            </div>

            {/* Log output */}
            <div className="relative">
                <div
                    ref={scrollRef}
                    onScroll={handleScroll}
                    className="h-64 overflow-y-auto font-mono text-xs bg-base-200 p-3 space-y-0.5"
                    style={{ resize: "vertical" }}
                >
                    {renderBody()}
                </div>

                {showScrollBtn.current && (
                    <button
                        type="button"
                        className="absolute bottom-3 right-4 btn btn-xs btn-neutral gap-1 opacity-90"
                        onClick={scrollToBottom}
                        title="Scroll to bottom"
                    >
                        <IconArrowDownToLine className="w-3 h-3" />
                        Bottom
                    </button>
                )}
            </div>
        </div>
    );
};
