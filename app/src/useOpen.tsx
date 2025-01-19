import { Command } from "@tauri-apps/plugin-shell";
import { isWindows } from "./utils";

export async function runOpen(args: string[]) {
    try {
        if (await isWindows()) {
            await Command.create("cmd", ['/c', 'start', ...args]).execute();
        } else {
            await Command.create("open", args).execute();
        }
    } catch (e) {
        console.error(e);
    }
}