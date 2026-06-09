import { useMemo } from "react";
import { Section } from "../Section";
import { useHarbor } from "../useHarbor";
import { Loader } from "../Loading";
import { IconButton } from "../IconButton";
import { IconRotateCW } from "../Icons";

const ANCHORS = {
    OK: "✔",
    NOK: "✘",
};

const ANCHOR_RE = new RegExp(
    `(${Object.values(ANCHORS).join("|")})\\s+(.*)$`,
);

export const Doctor = () => {
    const { result, loading, error, rerun } = useHarbor(["doctor"], { raw: true });
    const output = useMemo(() => {
        const out = result?.stderr ?? "";
        return out
            .split("\n")
            .filter((s) => s.trim())
            .filter((s) => {
                return s.includes(ANCHORS.OK) || s.includes(ANCHORS.NOK);
            })
            .map((s) => {
                const matches = s.match(ANCHOR_RE) ?? [];
                const [, status, message] = matches;

                return (
                    <div key={message} className="flex items-center gap-2">
                        <span
                            className={status === ANCHORS.OK
                                ? "text-success"
                                : "text-error"}
                        >
                            {status}
                        </span>
                        <span>{message}</span>
                    </div>
                );
            });
    }, [result]);

    return (
        <Section
            header={
                <>
                    <span>Doctor</span>
                    <IconButton icon={<IconRotateCW />} onClick={rerun} />
                </>
            }
            children={
                <>
                    <Loader loading={loading} />
                    {error && <span>{error.message}</span>}
                    <span>{output}</span>
                </>
            }
        />
    );
};
