import { Doctor } from "../home/Doctor";
import { Version } from "../home/Version";
import { CommandRunner } from "./CommandRunner";

export const CLI = () => {
    return (
        <>
            <Doctor />
            <Version />
            <CommandRunner />
        </>
    );
};
