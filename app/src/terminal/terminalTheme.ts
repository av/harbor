import type { ITheme } from "@xterm/xterm";

// Convert oklch(L C H) to sRGB hex without relying on browser CSS oklch support.
// DaisyUI v4 stores colors as bare oklch component strings e.g. "59.18% 0.15 58.9".
// Using a hidden DOM element + getComputedStyle fails on WebViews that don't support
// oklch() (common on older Linux WebKitGTK): the invalid assignment is silently dropped
// and getComputedStyle returns the inherited color (black), making everything #000000.

function oklchToHex(l: number, c: number, h: number): string {
    // oklch → oklab
    const hRad = (h * Math.PI) / 180;
    const a = c * Math.cos(hRad);
    const b = c * Math.sin(hRad);

    // oklab → linear sRGB  (standard oklab matrix)
    const lp = l + 0.3963377774 * a + 0.2158037573 * b;
    const mp = l - 0.1055613458 * a - 0.0638541728 * b;
    const sp = l - 0.0894841775 * a - 1.2914855480 * b;

    const lr = lp * lp * lp;
    const mg = mp * mp * mp;
    const sb = sp * sp * sp;

    const linR =  4.0767416621 * lr - 3.3077115913 * mg + 0.2309699292 * sb;
    const linG = -1.2684380046 * lr + 2.6097574011 * mg - 0.3413193965 * sb;
    const linB = -0.0041960863 * lr - 0.7034186147 * mg + 1.7076147010 * sb;

    // linear sRGB → gamma-compressed sRGB
    const toSrgb = (v: number): number => {
        const clamped = Math.max(0, Math.min(1, v));
        return clamped <= 0.0031308
            ? 12.92 * clamped
            : 1.055 * Math.pow(clamped, 1 / 2.4) - 0.055;
    };

    const r = Math.round(toSrgb(linR) * 255);
    const g = Math.round(toSrgb(linG) * 255);
    const bl = Math.round(toSrgb(linB) * 255);
    return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${bl.toString(16).padStart(2, "0")}`;
}

// Reads a DaisyUI CSS var from :root and converts to hex.
// DaisyUI v4 stores colors as bare oklch component strings e.g. "59.18% 0.15 58.9"
// (no `oklch()` wrapper). CSS var names: --b1, --b2, --b3, --bc, --p, --su, --er, --wa, --in.
function cssVarToHex(varName: string): string {
    const raw = getComputedStyle(document.documentElement)
        .getPropertyValue(varName)
        .trim();
    if (!raw) return "#000000";

    // Strip oklch() wrapper if present (some paths may produce it)
    const components = raw.startsWith("oklch(")
        ? raw.slice(6, -1).trim()
        : raw;

    // Expect "L% C H" — e.g. "59.18% 0.15 58.9"
    const parts = components.split(/\s+/);
    if (parts.length < 2) return "#000000";

    const l = parseFloat(parts[0]) / 100; // percentage → 0..1
    const c = parseFloat(parts[1]);
    const h = parseFloat(parts[2] ?? "0") || 0; // missing/NaN hue → 0

    if (isNaN(l) || isNaN(c)) return "#000000";

    return oklchToHex(l, c, h);
}

// Linear interpolation between two hex colors at ratio t (0 = a, 1 = b)
function mixHex(a: string, b: string, t = 0.5): string {
    const ar = parseInt(a.slice(1, 3), 16);
    const ag = parseInt(a.slice(3, 5), 16);
    const ab = parseInt(a.slice(5, 7), 16);
    const br = parseInt(b.slice(1, 3), 16);
    const bg = parseInt(b.slice(3, 5), 16);
    const bb = parseInt(b.slice(5, 7), 16);
    const r = Math.round(ar + (br - ar) * t);
    const g = Math.round(ag + (bg - ag) * t);
    const bv = Math.round(ab + (bb - ab) * t);
    return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${bv.toString(16).padStart(2, "0")}`;
}

export function buildXtermTheme(): ITheme {
    const bg = cssVarToHex("--b1");
    const fg = cssVarToHex("--bc");
    const cursor = cssVarToHex("--p");
    const selection = cssVarToHex("--b3");

    // Structural surface colors
    const b2 = cssVarToHex("--b2");
    const b3 = cssVarToHex("--b3");

    // Semantic status colors
    const success = cssVarToHex("--su");
    const error = cssVarToHex("--er");
    const warning = cssVarToHex("--wa");
    const info = cssVarToHex("--in");

    // Bright semantic variants: mix toward full foreground for a lighter highlight
    const brightSuccess = mixHex(success, fg, 0.3);
    const brightError = mixHex(error, fg, 0.3);
    const brightWarning = mixHex(warning, fg, 0.3);
    const brightInfo = mixHex(info, fg, 0.3);

    // Neutral midpoint for unsupported cyan/magenta slots
    const midSurface = mixHex(b3, fg, 0.5);

    return {
        background: bg,
        foreground: fg,
        cursor,
        cursorAccent: bg,
        selectionBackground: selection,

        // Monochromatic/structural
        black:        bg,
        brightBlack:  b3,
        white:        b2,
        brightWhite:  fg,

        // Semantic status
        green:        success,
        brightGreen:  brightSuccess,
        red:          error,
        brightRed:    brightError,
        yellow:       warning,
        brightYellow: brightWarning,
        blue:         info,
        brightBlue:   brightInfo,

        // Unsupported slots — collapsed to neutral greys
        cyan:         b3,
        brightCyan:   midSurface,
        magenta:      b3,
        brightMagenta: midSurface,
    };
}

// Call once — returns cleanup function
export function watchTheme(onThemeChange: () => void): () => void {
    const observer = new MutationObserver((mutations) => {
        for (const m of mutations) {
            if (m.type === "attributes" && m.attributeName === "data-theme") {
                onThemeChange();
                break;
            }
        }
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
}
