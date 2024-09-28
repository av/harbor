export const readLocalStorage = <T extends unknown>(
    key: string,
    defaultValue: T,
): T => {
    const item = localStorage.getItem(key);
    if (item !== null) {
        try {
            return JSON.parse(item) as T;
        } catch (e) {
            console.error(
                `Error parsing localStorage item with key "${key}":`,
                e,
            );
        }
    }
    return defaultValue;
};

export const writeLocalStorage = <T>(key: string, newState: T) => {
    try {
        localStorage.setItem(key, JSON.stringify(newState));
    } catch (e) {
        console.error(`Error writing to localStorage with key "${key}":`, e);
    }
};

export const deleteLocalStorage = (key: string) => {
    try {
        localStorage.removeItem(key);
    } catch (e) {
        console.error(`Error deleting localStorage item with key "${key}":`, e);
    }
};

export const hasKey = (key: string): boolean => {
    return localStorage.getItem(key) !== null;
};
