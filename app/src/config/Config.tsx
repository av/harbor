import { FC, useEffect } from "react";
import { useHarborConfig } from "./useHarborConfig";
import { ProfileSelector } from "../settings/ProfileSelector";
import { Loader } from "../Loading";
import { ScrollToTop } from "../ScrollToTop";
import { useSharedState } from "../useSharedState";

export const Config: FC = () => {
  const { configs: profiles, loading } = useHarborConfig();
  const [, setConfigDeepLink] = useSharedState<string | null>("configDeepLink", null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const service = params.get("service");

    if (service) {
      setConfigDeepLink(service);
      params.delete("service");
      const newSearch = params.toString();
      const newUrl = window.location.pathname + (newSearch ? `?${newSearch}` : "");
      history.replaceState(null, "", newUrl);
    }

    return () => {
      setConfigDeepLink(null);
    };
  }, []);

  return (
    <>
      <Loader loading={loading} />
      <ProfileSelector configs={profiles} />
      <ScrollToTop />
    </>
  );
};
