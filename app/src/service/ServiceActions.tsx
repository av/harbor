import { useState } from 'react';

import { IconButton } from '../IconButton';
import { HarborService, HST } from '../serviceMetadata'
import { runHarbor } from '../useHarbor';
import { markHandled, resolveResultLines, toasted } from '../utils';
import { ACTION_ICONS } from '../serviceActions';
import { IconBookMarked, IconExternalLink } from '../Icons';
import { runOpen } from '../useOpen';

export const ServiceActions = ({
  service,
  onUpdate,
}: {
  service: HarborService,
  onUpdate?: () => void,
}) => {
  const [loading, setLoading] = useState(false);

  const openService = async (e: React.MouseEvent) => {
    markHandled(e);

    const urlResult = await runHarbor(["url", service.handle]);
    const url = resolveResultLines(urlResult).join("");
    await runOpen([url]);
  };

  const toggleService = (e: React.MouseEvent) => {
    markHandled(e);

    const msg = (str: string) => (
      <span>
        <span className="font-bold mr-2">{service.name ?? service.handle}</span>
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
        onUpdate?.();
      },
    });
  };

  const handleWikiClick = (e: React.MouseEvent) => {
    markHandled(e);
  }

  const canLaunch = !service.tags.includes(HST.cli);

  const actionIcon = loading
    ? ACTION_ICONS.loading
    : service.isRunning
      ? ACTION_ICONS.down
      : ACTION_ICONS.up;

  return <>
    {
      canLaunch && (
        <>
          {service.isRunning && (
            <span className="inline-block bg-success shrink-0 w-2 h-2 rounded-full">
            </span>
          )}
          {!service.isRunning && (
            <span className="inline-block bg-base-content/20 shrink-0 w-2 h-2 rounded-full">
            </span>
          )}
          <IconButton
            disabled={loading}
            icon={actionIcon}
            onClick={toggleService}
          />
        </>
      )
    }

    <div className="flex-1 min-w-4"></div>
    {
      service.isRunning && (
        <IconButton
          icon={<IconExternalLink />}
          onClick={openService}
        />
      )
    }
    {
      service.wikiUrl && (
        <a
          className="text-base-content/50 btn btn-sm btn-circle"
          href={service.wikiUrl}
          target="_blank"
          rel="noreferrer"
          onClick={handleWikiClick}
        >
          <IconBookMarked />
        </a>
      )
    }
  </>
}