import { Command } from "@tauri-apps/plugin-shell";
import { getOSPlatform } from "./utils";

export async function runOpen(args: string[]) {
    try {
        const os = await getOSPlatform();

        if (os === "windows") {
            await Command.create("cmd", ['/c', 'start', ...args]).execute();
        } else if (os === "linux") {
            await Command.create("xdg-open", args).execute();
        } else {
            await Command.create("open", args).execute();
        }
    } catch (e) {
        console.error(e);
    }
}