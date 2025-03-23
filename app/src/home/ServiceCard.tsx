import { HarborService } from "../serviceMetadata";
import { ServiceTags } from "../ServiceTags";
import { HST } from "../serviceMetadata";
import { HSTColors } from "../ServiceTags";
import { HSTColorOpts } from "../ServiceTags";
import { isHandled } from "../utils";
import { useNavigate } from "react-router-dom";
import { ServiceActions } from "../service/ServiceActions";
import { ServiceName } from '../service/ServiceName';

export const ServiceCard = ({
  service,
  onUpdate,
}: {
  service: HarborService;
  onUpdate: () => void;
}) => {
  const navigate = useNavigate();

  const handleCardClick = (e: React.MouseEvent) => {
    if (isHandled(e)) {
      return;
    }

    navigate(`/services/${service.handle}`);
  };

  const gradientTag = service.tags.find((t) => HSTColorOpts.includes(t as HST));

  const gradientClass = gradientTag
    ? `bg-gradient-to-tr from-0% to-50% ${HSTColors[gradientTag]}`
    : "";

  return (
    <div
      className={`p-4 rounded-box bg-base-200/50 hover:bg-base-200 relative tooltip tooltip-top label-text cursor-pointer ${gradientClass}`}
      data-tip={service.tooltip}
      onClick={handleCardClick}
    >
      <h2 className="flex items-center gap-1 text-2xl pb-2">
        <ServiceName service={service} />
        <ServiceActions service={service} onUpdate={onUpdate} />
      </h2>
      <ServiceTags service={service} />
    </div>
  );
};
