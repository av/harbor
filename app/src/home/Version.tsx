import { Loader } from "../Loading";
import { Section } from "../Section";
import { useHarbor } from "../useHarbor";
import { resolveResultLines } from "../utils";

export const Version = () => {
    const { result, loading, error } = useHarbor(["--version"]);
    const output = resolveResultLines(result);

    return (
        <Section
            className="mt-6"
            header="Version"
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
