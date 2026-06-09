import { ButtonHTMLAttributes, ReactNode } from "react";

type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
    icon: ReactNode;
};

export const IconButton = (
    { className, icon, ...rest }: IconButtonProps,
) => {
    return (
        <button
            type="button"
            className={`btn btn-sm btn-circle text-base-content/70 ${className}`}
            {...rest}
        >
            {icon}
        </button>
    );
};
