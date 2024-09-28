import { useRef } from "react";
import { IconButton } from "./IconButton";
import { IconArrowUpToLine } from "./Icons";

function getClosestScrollableParent(element: EventTarget) {
    let parent = (element as HTMLElement).parentElement;
    while (parent) {
        if (
            parent.scrollHeight > parent.clientHeight
        ) {
            return parent;
        }
        parent = parent.parentElement;
    }
    return null;
}

export const ScrollToTop = () => {
    const anchorRef = useRef<HTMLAnchorElement>(null);

    return (
        <>
            <a ref={anchorRef} className="relative top-0 left-0"></a>
            <IconButton
                className="fixed bottom-4 right-4 text-2xl btn-md z-50"
                icon={<IconArrowUpToLine />}
                onClick={(e) => {
                    e.preventDefault();
                    const parent = getClosestScrollableParent(e.target);

                    if (parent) {
                        parent.scrollTo({
                            top: 0,
                            behavior: "smooth",
                        });
                    } else {
                        window.scrollTo({
                            top: 0,
                            behavior: "smooth",
                        });
                    }
                }}
            />
        </>
    );
};
