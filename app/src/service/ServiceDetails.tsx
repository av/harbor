import { useState } from "react";
import { Loader } from "../Loading";
import { ServiceName } from "./ServiceName";
import { ServiceActions } from "./ServiceActions";
import { ServiceTags } from "../ServiceTags";
import { ServiceDescription } from "./ServiceDescription";
import { useCurrentService } from "./useCurrentService";
import { ServiceDocs } from "./ServiceDocs";
import { ServiceHandle } from './ServiceHandle';
import { ScrollToTop } from '../ScrollToTop';
import { BackButton } from '../BackButton';
import { useNavigate } from "react-router-dom";
import { IconSettings, IconTerminal } from "../Icons";
import { ServiceLogs } from "./ServiceLogs";

export const ServiceDetails = () => {
  const info = useCurrentService();
  const navigate = useNavigate();
  const [logsOpen, setLogsOpen] = useState(false);

  const handleConfigure = () => {
    if (info.service) {
      navigate(`/config?service=${encodeURIComponent(info.service.handle)}`);
    }
  };

  const handleLogsToggle = () => {
    setLogsOpen((prev) => !prev);
  };

  const handleLogsClose = () => {
    setLogsOpen(false);
  };

  return (
    <div className='max-w-4xl'>
      <Loader loading={info.loading} loader="overlay" />
      {info.service && (
        <div className="flex flex-col gap-4">
          <h2 className="flex items-center gap-2 text-2xl pb-2">
            <BackButton />
            <ServiceName service={info.service} />
            <ServiceActions service={info.service} onUpdate={info.rerun} />
          </h2>
          <div className='flex flex-row gap-2'>
            <ServiceHandle service={info.service} />
            <ServiceTags service={info.service} />
          </div>
          <div className="flex flex-row gap-2">
            <button
              className="btn btn-sm btn-outline gap-2"
              onClick={handleConfigure}
            >
              <IconSettings className="w-4 h-4" />
              Configure
            </button>
            {info.service.isRunning && (
              <button
                className={`btn btn-sm btn-outline gap-2 ${logsOpen ? "btn-active" : ""}`}
                onClick={handleLogsToggle}
              >
                <IconTerminal className="w-4 h-4" />
                Logs
              </button>
            )}
          </div>
          {logsOpen && (
            <ServiceLogs service={info.service} onClose={handleLogsClose} />
          )}
          <ServiceDescription service={info.service} />
          <ServiceDocs service={info.service} />
        </div>
      )}
      <ScrollToTop />
    </div>
  );
};
