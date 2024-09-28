import { FC } from "react";
import { useHarborConfig } from "./useHarborConfig";
import { ProfileSelector } from "../settings/ProfileSelector";
import { LinearLoader } from "../LinearLoading";
import { ScrollToTop } from "../ScrollToTop";

export const Config: FC = () => {
  const { configs: profiles, loading } = useHarborConfig();

  return (
    <>
      <LinearLoader loading={loading} />
      <ProfileSelector configs={profiles} />
      <ScrollToTop />
    </>
  );
};
