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

export const Doctor = () => {
    const { result, loading, error, rerun } = useHarbor(["doctor"]);
    const output = useMemo(() => {
        const out = result?.stderr ?? "";
        const items = out
            .split("\n")
            .filter((s) => s.trim())
            .filter((s) => {
                return s.includes(ANCHORS.OK) || s.includes(ANCHORS.NOK);
            })
            .map((s) => {
                const matches = s.match(
                    new RegExp(
                        `(${Object.values(ANCHORS).join("|")})\\s+(.*)$`,
                    ),
                ) ?? [];
                const [_, status, message] = matches;

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

        return items.map((item, index) => <div key={index}>{item}</div>);
    }, [result]);

    return (
        <Section
            className=""
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
