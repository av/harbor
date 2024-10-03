import { useEffect, useState } from 'react';

export const TOGGLE_DELAY = 250;

export const LoaderElements = {
    linear: <progress className="progress my-2 max-w-56"></progress>,
    overlay: (
        <div className="absolute inset-0 p-6 flex items-center justify-center bg-base-200/60 pointer-events-none rounded-box">
            <progress className="progress"></progress>
        </div>
    ),
}

export const Loader = ({ loading, loader = "linear" }: { loading: boolean, loader?: keyof typeof LoaderElements }) => {
    const [showLoader, setShowLoader] = useState(false);
    const loaderComponent = LoaderElements[loader];

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

    return loaderComponent;
};
