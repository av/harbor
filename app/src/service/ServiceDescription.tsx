import { HarborService } from '../serviceMetadata';

export const ServiceDescription = ({ service }: { service: HarborService }) => {
  return (
    <div>
      <p>{service.tooltip}</p>
    </div>
  );
}