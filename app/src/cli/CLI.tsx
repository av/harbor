import { Section } from "../Section";
import { Doctor } from "../home/Doctor";
import { IconButton } from "../IconButton";
import { IconArrowDownToLine, IconRotateCW } from "../Icons";
import { useHarborSetup } from "../setup/HarborSetupContext";

export const CLI = () => {
    const setup = useHarborSetup();

    return (
        <>
            <Section
                header={
                    <>
                        <span>Version</span>
                        <IconButton
                            icon={<IconRotateCW />}
                            onClick={setup.redetect}
                            disabled={setup.loading || setup.running}
                        />
                    </>
                }
                children={
                    <div className="flex items-center gap-3">
                        <span className="text-base-content/60">
                            {setup.detail?.cliVersion ?? "not installed"}
                        </span>
                        <button
                            className="btn btn-xs btn-outline"
                            onClick={setup.startSetup}
                            disabled={setup.loading || setup.running}
                        >
                            <IconArrowDownToLine />
                            Reinstall
                        </button>
                    </div>
                }
            />
            <Doctor />
        </>
    );
};
