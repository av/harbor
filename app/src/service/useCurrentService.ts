import { useParams } from 'react-router-dom';
import { useServiceList } from '../home/useServiceList';

export const useCurrentService = () => {
  const params = useParams()
  const handle = params.handle;
  const services = useServiceList()
  const service = services.services.find((service) => service.handle === handle);

  return {
    service,
    loading: services.loading,
    rerun: services.rerun,
  }
}