import { FC } from "react";
import { useHarborConfig } from "./useHarborConfig";
import { ProfileSelector } from "../settings/ProfileSelector";
import { Loader } from "../Loading";
import { ScrollToTop } from "../ScrollToTop";

export const Config: FC = () => {
  const { configs: profiles, loading } = useHarborConfig();

  return (
    <>
      <Loader loading={loading} />
      <ProfileSelector configs={profiles} />
      <ScrollToTop />
    </>
  );
};
