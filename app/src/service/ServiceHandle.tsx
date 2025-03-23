import { IconTerminal } from "../Icons";
import { HarborService } from "../serviceMetadata";

export const ServiceHandle = ({ service }: { service: HarborService }) => {
  return (
    <div
      className="flex flex-row items-center gap-2 justify-center text-base-content/75 bg-base-300/50 px-2 rounded-badge tooltip tooltip-right text-sm"
      data-tip="Service handle in Harbor CLI"
    >
      <IconTerminal />
      <span className="">{service.handle}</span>
    </div>
  );
};
