import { useEffect, useState } from 'react';

export const TOGGLE_DELAY = 250;

export const LinearLoader = ({ loading }: { loading: boolean }) => {
    const [showLoader, setShowLoader] = useState(false);

    useEffect(() => {
        let timer: number;

        if (loading) {
            timer = setTimeout(() => setShowLoader(true), TOGGLE_DELAY);
        } else {
            setShowLoader(false);
        }
        return () => clearTimeout(timer);
    }, [loading]);

    if (!showLoader) return null;

    return <progress className="progress my-2 max-w-56"></progress>;
};
