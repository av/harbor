import { SVGProps } from "react";

import { IconSquirrel } from "./Icons";
import './squirrel.css';

export const LostSquirrel = ({ className, ...rest }: SVGProps<SVGSVGElement>) => {
    return <IconSquirrel className={`squirrel-icon ${className}`} {...rest} />;
};
