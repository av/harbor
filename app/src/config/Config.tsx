import { FC, useEffect } from "react";
import { useHarborConfig } from "./useHarborConfig";
import { ProfileSelector } from "../settings/ProfileSelector";
import { Loader } from "../Loading";
import { ScrollToTop } from "../ScrollToTop";
import { useSharedState } from "../useSharedState";
import { errorMessage } from "../utils";

export const Config: FC = () => {
  const { configs: profiles, loading, error } = useHarborConfig();
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
      {error && (
        <div className="alert alert-error text-sm">
          <span>Failed to load profiles: {errorMessage(error)}</span>
        </div>
      )}
      <ProfileSelector configs={profiles} />
      <ScrollToTop />
    </>
  );
};
