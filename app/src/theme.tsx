import themes from "daisyui/src/theming/themes";

import * as localStorage from "./localStorage";
import { useCallback } from "react";
import { useStoredState } from "./useStoredState";

export const DEFAULT_THEME = "harborLight";
export const THEMES = [
  "harborLight",
  "harborDark",
  ...Object.keys(themes),
];

export const getTheme = () => {
    return localStorage.readLocalStorage('theme', DEFAULT_THEME);
}

export const setTheme = (newTheme: string) => {
    const themeRoot = document.documentElement;
    if (themeRoot) {
        themeRoot.setAttribute('data-theme', newTheme);
    }
}

export const init = () => {
    const theme = getTheme();
    setTheme(theme);
}

export const useTheme = (): [string, (newTheme: string) => void] => {
    const [theme, setThemeState] = useStoredState('theme', DEFAULT_THEME);

    const changeTheme = useCallback((newTheme: string) => {
        setTheme(newTheme);
        setThemeState(newTheme);
    }, []);

    return [theme, changeTheme];
}