import { useState } from "react";
import { IconButton } from "../IconButton";
import { IconBookMarked, IconExternalLink } from "../Icons";
import { ACTION_ICONS, HarborService } from "../serviceMetadata";
import { HST, ServiceTags } from "../ServiceTags";
import { HSTColors } from "../ServiceTags";
import { HSTColorOpts } from "../ServiceTags";
import { runHarbor } from "../useHarbor";
import { toasted } from "../utils";

export const ServiceCard = (
  { service, onUpdate }: { service: HarborService; onUpdate: () => void },
) => {
  const [loading, setLoading] = useState(false);

  const openService = () => {
    runHarbor(["open", service.handle]);
  };

  const toggleService = () => {
    const msg = (str: string) => (
      <span>
        <span className="font-bold mr-2">{service.handle}</span>
        <span>{str}</span>
      </span>
    );

    const action = () => {
      setLoading(true);
      return runHarbor([
        service.isRunning ? "down" : "up",
        service.handle,
      ]);
    };
    const ok = service.isRunning ? msg("stopped") : msg("started");
    const error = service.isRunning
      ? msg("failed to stop")
      : msg("failed to start");

    toasted({
      action,
      ok,
      error,
      finally() {
        setLoading(false);
        onUpdate();
      },
    });
  };

  const actionIcon = loading
    ? ACTION_ICONS.loading
    : service.isRunning
    ? ACTION_ICONS.down
    : ACTION_ICONS.up;

  const canLaunch = !service.tags.includes(HST.cli);
  const gradientTag = service.tags.find((t) => HSTColorOpts.includes(t as HST));

  const gradientClass = gradientTag
    ? `bg-gradient-to-tr from-0% to-50% ${HSTColors[gradientTag]}`
    : "";

  return (
    <div
      className={`p-4 rounded-box cursor-default bg-base-200/50 relative ${gradientClass}`}
    >
      <h2 className="flex items-center gap-1 text-2xl pb-2">
        <span className="font-bold">{service.handle}</span>

        {canLaunch && (
          <>
            {service.isRunning && (
              <span className="inline-block bg-success w-2 h-2 rounded-full">
              </span>
            )}
            {!service.isRunning && (
              <span className="inline-block bg-base-content/20 w-2 h-2 rounded-full">
              </span>
            )}
            <IconButton
              disabled={loading}
              icon={actionIcon}
              onClick={toggleService}
            />
          </>
        )}

        <div className="flex-1 min-w-4"></div>
        {service.isRunning && (
          <IconButton
            icon={<IconExternalLink />}
            onClick={openService}
          />
        )}
        {service.wikiUrl && (
          <a
            className="text-base-content/50 btn btn-sm btn-circle"
            href={service.wikiUrl}
            target="_blank"
            rel="noreferrer"
          >
            <IconBookMarked />
          </a>
        )}
      </h2>
      <ServiceTags service={service} />
    </div>
  );
};
