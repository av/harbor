import { HTMLProps } from "react";

export type SectionProps = HTMLProps<HTMLDivElement> & {
    header: React.ReactNode;
    children: React.ReactNode;
};

export const Section = ({ header, children, ...rest }: SectionProps) => {
    return (
        <div {...rest}>
            <h1 className="text-xl font-semibold flex items-center gap-2 mb-2">
                {header}
            </h1>
            {children}
        </div>
    );
};
