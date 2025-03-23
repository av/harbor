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

export const ServiceDetails = () => {
  const info = useCurrentService();

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
          <ServiceDescription service={info.service} />
          <ServiceDocs service={info.service} />
        </div>
      )}
      <ScrollToTop />
    </div>
  );
};
