import { HarborService } from "../serviceMetadata";

export const ServiceName = ({ service }: { service: HarborService }) => {
  return (
    <span className="font-bold shrink-1">{service.name ?? service.handle}</span>
  );
};
