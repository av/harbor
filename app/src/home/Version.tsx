import { LinearLoader } from "../LinearLoading";
import { Section } from "../Section";
import { useHarbor } from "../useHarbor";

export const Version = () => {
    const { result, loading, error } = useHarbor(["--version"]);

    return (
        <Section
            className="mt-6"
            header="Version"
            children={
                <>
                    <LinearLoader loading={loading} />
                    {error && <span>{error.message}</span>}
                    <span>{result?.stdout}</span>
                </>
            }
        />
    );
};
