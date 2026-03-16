import { HarborService } from "../serviceMetadata";
import { ServiceTags } from "../ServiceTags";
import { HST } from "../serviceMetadata";
import { HSTColors } from "../ServiceTags";
import { HSTColorOpts } from "../ServiceTags";
import { isHandled, markHandled } from "../utils";
import { useNavigate } from "react-router-dom";
import { ServiceActions } from "../service/ServiceActions";
import { ServiceName } from '../service/ServiceName';
import { IconPin, IconPinOff } from "../Icons";

export const ServiceCard = ({
  service,
  onUpdate,
  isPinned,
  onTogglePin,
}: {
  service: HarborService;
  onUpdate: () => void;
  isPinned?: boolean;
  onTogglePin?: (handle: string) => void;
}) => {
  const navigate = useNavigate();

  const handleCardClick = (e: React.MouseEvent) => {
    if (isHandled(e)) {
      return;
    }

    navigate(`/services/${service.handle}`);
  };

  const handlePinClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    markHandled(e);
    onTogglePin?.(service.handle);
  };

  const gradientTag = service.tags.find((t) => HSTColorOpts.includes(t as HST));

  const gradientClass = gradientTag
    ? `bg-gradient-to-tr from-0% to-50% ${HSTColors[gradientTag]}`
    : "";

  return (
    <div
      className={`group p-4 rounded-box bg-base-200/50 hover:bg-base-200 relative tooltip tooltip-top label-text cursor-pointer ${gradientClass}`}
      data-tip={service.tooltip}
      onClick={handleCardClick}
    >
      <h2 className="flex items-center gap-1 text-2xl pb-2">
        <ServiceName service={service} />
        {!service.tags.includes(HST.cli) && (
          <span className={`inline-block shrink-0 w-2 h-2 rounded-full ${service.isRunning ? "bg-success" : "bg-base-content/20"}`} />
        )}
        <span className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 [&_.service-status-dot]:hidden">
          <ServiceActions service={service} onUpdate={onUpdate} />
        </span>
        {onTogglePin && (
          <button
            className="btn btn-ghost btn-xs btn-circle ml-1 text-base-content/40 hover:text-base-content opacity-0 group-hover:opacity-100 transition-opacity"
            onClick={handlePinClick}
            aria-label={isPinned ? "Unpin service" : "Pin service"}
          >
            {isPinned ? <IconPinOff className="w-4 h-4" /> : <IconPin className="w-4 h-4" />}
          </button>
        )}
      </h2>
      <ServiceTags service={service} />
    </div>
  );
};
