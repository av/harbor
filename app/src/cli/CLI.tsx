import { Doctor } from "../home/Doctor";
import { Version } from "../home/Version";

export const CLI = () => {
    return (
        <>
            <Doctor />
            <Version />
            <p className="text-sm text-base-content/50 mt-4">
                Use the terminal panel to run commands. Press the terminal icon in the navbar to open it.
            </p>
        </>
    );
};
