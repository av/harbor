import themes, { dark } from "daisyui/src/theming/themes";

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./src/index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [
    require("@tailwindcss/typography"),
    require("daisyui"),
  ],
  darkMode: [
    "selector",
    '[data-theme="night"]',
    '[data-theme="sunset"]',
    '[data-theme="dark"]',
  ],
  safelist: ["dark", "sunset"],
  daisyui: {
    themes: [
      {
        harborLight: {
          ...themes.lofi,
          success: "#12A71F",
        },
        harborDark: {
          ...themes.black,
          primary: '#ccc',
          secondary: '#ccc',
          accent: '#ccc',
          success: "#12A71F",
          info: themes.lofi.info,
          warning: themes.lofi.warning,
          error: themes.lofi.error,
          ...Object.fromEntries(
            Object.entries(themes.lofi).filter(([key]) => key.startsWith('--')),
          ),
        },
      },
      ...Object.keys(themes)
    ],
    dark: false,
    base: true,
    styled: true,
    utils: true,
    prefix: "",
    logs: true,
    themeRoot: ":root",
  },
};
