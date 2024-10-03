import themes from "daisyui/src/theming/themes";

import * as localStorage from "./localStorage";
import { useCallback, useRef } from "react";
import { useStoredState } from "./useStoredState";

export const DEFAULT_THEME = "harborLight";

// "dim" theme crashes tauri app host
// due to unexplainable reasons, so removing it
// from the list of available themes permanently
export const DISABLED_THEMES = new Set(['dim'])

export const THEMES = [
    "harborLight",
    "harborDark",
    ...Object.keys(themes).filter((theme) => !DISABLED_THEMES.has(theme)),
];

export const DEFAULT_THEME_STATE = {
    theme: DEFAULT_THEME,
    hue: 0,
    saturation: 100,
    contrast: 100,
    brightness: 100,
    invert: 0,
};

export const getTheme = () => {
    return localStorage.readLocalStorage<typeof DEFAULT_THEME_STATE>('themeState', DEFAULT_THEME_STATE);
}

export const setTheme = (theme: typeof DEFAULT_THEME_STATE) => {
    const themeRoot = document.documentElement;

    if (themeRoot) {
        themeRoot.setAttribute('data-theme', theme.theme);
    }

    const filterRoot = document.body;

    if (filterRoot) {
        const parts = [
            `hue-rotate(${theme.hue}deg)`,
            `saturate(${theme.saturation}%)`,
            `contrast(${theme.contrast}%)`,
            `brightness(${theme.brightness}%)`,
            `invert(${theme.invert}%)`,
        ]

        document.body.style.filter = parts.join(' ');
    }
}

export const init = () => {
    setTheme(getTheme());
}

export const useTheme = () => {
    const [theme, setThemeState] = useStoredState('themeState', DEFAULT_THEME_STATE);
    const themeRef = useRef(theme);
    themeRef.current = theme;

    const updateTheme = useCallback((newTheme: typeof DEFAULT_THEME_STATE) => {
        setTheme(newTheme);
        setThemeState(newTheme);
    }, []);

    const changeTheme = useCallback((newTheme: string) => {
        updateTheme({ ...themeRef.current, theme: newTheme });
    }, []);

    const changeHue = useCallback((newHue: number) => {
        updateTheme({ ...themeRef.current, hue: newHue });
    }, []);

    const changeSaturation = useCallback((newSaturation: number) => {
        updateTheme({ ...themeRef.current, saturation: newSaturation });
    }, []);

    const changeContrast = useCallback((newContrast: number) => {
        updateTheme({ ...themeRef.current, contrast: newContrast });
    }, []);

    const changeBrightness = useCallback((newBrightness: number) => {
        updateTheme({ ...themeRef.current, brightness: newBrightness });
    }, []);

    const changeInvert = useCallback((newInvert: number) => {
        updateTheme({ ...themeRef.current, invert: newInvert });
    }, []);

    return {
        ...theme,
        reset: () => updateTheme(DEFAULT_THEME_STATE),
        setTheme: changeTheme,
        setHue: changeHue,
        setSaturation: changeSaturation,
        setContrast: changeContrast,
        setBrightness: changeBrightness,
        setInvert: changeInvert,
    };
}