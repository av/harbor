import { useNavigate } from "react-router-dom";

import { IconButton } from "./IconButton";
import { IconMoveLeft } from "./Icons";

export const BackButton = () => {
  const navigate = useNavigate();
  const handleBack = () => navigate(-1);

  return <IconButton icon={<IconMoveLeft />} onClick={handleBack} />;
};
