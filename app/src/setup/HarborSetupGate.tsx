import { FC, FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import { IconPlay, IconStop, IconWiRefreshAlt } from "../Icons";
import { HarborLogo } from "../HarborLogo";
import { useHarborSetup } from "./HarborSetupContext";

const stageLabels: Record<string, string> = {
  checking: "Checking",
  "not-installed": "Harbor CLI not installed",
  "checking-platform": "Checking platform",
  "installing-prerequisites": "Installing prerequisites",
  "installing-cli": "Installing Harbor CLI",
  "verifying-cli": "Verifying installation",
  ready: "Ready",
  blocked: "Blocked",
  failed: "Setup failed",
  cancelled: "Cancelled",
  "refresh-required": "Restart required",
};

export const HarborSetupGate: FC<{ children: ReactNode }> = ({ children }) => {
  const setup = useHarborSetup();
  const outputRef = useRef<HTMLDivElement>(null);
  const [input, setInput] = useState("");

  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight;
    }
  }, [setup.terminalOutput]);

  if (setup.ready) return <>{children}</>;

  const status = setup.detail?.status ?? "checking";
  const label = stageLabels[status] ?? status;
  const canInstall =
    !setup.loading &&
    !setup.running &&
    (status === "not-installed" || status === "failed" || status === "cancelled");

  const sendInput = async (e: FormEvent) => {
    e.preventDefault();
    if (!setup.running || !input) return;
    try {
      await setup.writeSetupInput(input + "\n");
      setInput("");
    } catch {
      // Error surfaces through the context
    }
  };

  return (
    <div className="flex h-screen flex-col bg-base-100 text-base-content">
      <div className="flex items-center justify-between border-b-2 border-base-content/10 px-6 py-4">
        <HarborLogo />
        <button
          className="btn btn-sm btn-ghost"
          onClick={setup.redetect}
          disabled={setup.loading || setup.running}
        >
          <IconWiRefreshAlt /> Check
        </button>
      </div>

      <div className="flex flex-1 flex-col gap-4 overflow-hidden px-6 py-4">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold">{label}</h1>
          {(setup.loading || setup.running) && (
            <span className="loading loading-spinner loading-sm" />
          )}
        </div>

        {(setup.error || setup.detail?.lastError) && (
          <div className="rounded border border-error/40 bg-error/10 p-3 text-sm">
            {setup.error ?? setup.detail?.lastError}
          </div>
        )}

        {status === "refresh-required" && (
          <div className="rounded border border-warning/40 bg-warning/10 p-3 text-sm">
            Harbor is installed but the app cannot find it in PATH. Restart
            Harbor App to pick up the new installation.
          </div>
        )}

        <div
          ref={outputRef}
          className="flex-1 overflow-auto rounded bg-neutral p-3 font-mono text-sm text-neutral-content"
        >
          {setup.terminalOutput ? (
            <pre className="whitespace-pre-wrap break-words">
              {setup.terminalOutput}
            </pre>
          ) : (
            <div className="text-neutral-content/50">
              Setup output will appear here.
            </div>
          )}
        </div>

        <form className="flex gap-2" onSubmit={sendInput}>
          <input
            className="input input-sm input-bordered min-w-0 flex-1 font-mono"
            type="password"
            value={input}
            placeholder="installer input"
            autoComplete="off"
            disabled={!setup.running}
            onChange={(e) => setInput(e.target.value)}
          />
          <button
            className="btn btn-sm btn-outline"
            type="submit"
            disabled={!setup.running || !input}
          >
            <IconPlay /> Send
          </button>
        </form>

        <div className="flex gap-2 pb-2">
          {setup.running ? (
            <button className="btn btn-sm btn-outline" onClick={setup.cancelSetup}>
              <IconStop /> Cancel
            </button>
          ) : (
            <button
              className="btn btn-sm btn-primary"
              disabled={!canInstall}
              onClick={setup.startSetup}
            >
              <IconPlay />
              {status === "failed" || status === "cancelled"
                ? "Retry"
                : "Install Harbor"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
