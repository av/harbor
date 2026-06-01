import { FC, FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import {
  IconCheck,
  IconCopy,
  IconExternalLink,
  IconOctagonAlert,
  IconPlay,
  IconStop,
  IconWiRefreshAlt,
} from "../Icons";
import { HarborLogo } from "../HarborLogo";
import { isFirstRunStackRemediation, useHarborSetup } from "./HarborSetupContext";

const HARBOR_INSTALL_URL =
  "https://raw.githubusercontent.com/av/harbor/refs/heads/main/install.sh";
const HARBOR_WINDOWS_INSTALL_URL =
  "https://raw.githubusercontent.com/av/harbor/refs/heads/main/install.ps1";

const stageLabels: Record<string, string> = {
  "checking-platform": "Checking platform",
  "checking-prerequisites": "Checking prerequisites",
  "installing-prerequisites": "Installing prerequisites",
  "checking-cli": "Checking Harbor CLI",
  "installing-cli": "Installing Harbor CLI",
  "refresh-required": "Refresh required",
  "verifying-cli": "Verifying Harbor CLI",
  "configuring-first-run-stack": "Configuring first-run stack",
  "starting-first-run-stack": "Starting first-run stack",
  "verifying-inference": "Verifying inference",
  ready: "Ready",
  blocked: "Blocked",
  failed: "Failed",
  cancelled: "Cancelled",
};

function actionLabel(status: string, remediationKind?: string | null) {
  if (status === "cancelled" || status === "failed") return "Retry setup";
  if (
    status === "configuring-first-run-stack" ||
    status === "starting-first-run-stack" ||
    status === "verifying-inference"
  ) {
    return "Start first-run stack";
  }
  if (status === "blocked" && remediationKind === "docker-daemon-unreachable") {
    return "Repair Docker setup";
  }
  if (status === "refresh-required" || status === "blocked") return "Resume check";
  return "Set up Harbor";
}

function setupActionLabel(status: string, remediationKind?: string | null) {
  if (isFirstRunStackRemediation(remediationKind)) {
    return "Start first-run stack";
  }

  return actionLabel(status, remediationKind);
}

function manualSetupCommand(platform?: string) {
  if (platform === "windows") {
    return `powershell -NoProfile -ExecutionPolicy Bypass -Command "iwr -UseBasicParsing '${HARBOR_WINDOWS_INSTALL_URL}' | iex"`;
  }

  return `curl -fsSL ${HARBOR_INSTALL_URL} | bash`;
}

export const HarborSetupGate: FC<{ children: ReactNode }> = ({ children }) => {
  const setup = useHarborSetup();
  const outputRef = useRef<HTMLDivElement>(null);
  const [installerInput, setInstallerInput] = useState("");

  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight;
    }
  }, [setup.logs, setup.terminalOutput]);

  if (setup.ready) {
    return <>{children}</>;
  }

  const detail = setup.detail;
  const status = detail?.status ?? "checking-platform";
  const currentStage = stageLabels[status] ?? status;
  const canRun = !setup.loading && !setup.running && status !== "ready";
  const isBlocked = status === "blocked" || status === "refresh-required";
  const manualCommand = manualSetupCommand(detail?.platform);
  const sendInstallerInput = async (event: FormEvent) => {
    event.preventDefault();
    if (!setup.running || installerInput.length === 0) return;
    try {
      await setup.writeSetupInput(`${installerInput}\n`);
      setInstallerInput("");
    } catch {
      // The provider surfaces the backend error in the setup error panel.
    }
  };

  return (
    <div className="min-h-screen bg-base-100 text-base-content">
      <div className="mx-auto flex min-h-screen w-full max-w-5xl flex-col px-6 py-5">
        <div className="mb-6 flex items-center justify-between border-b-2 border-base-content/10 pb-4">
          <HarborLogo />
          <button
            type="button"
            className="btn btn-sm btn-ghost"
            onClick={setup.redetect}
            disabled={setup.loading || setup.running}
          >
            <IconWiRefreshAlt />
            Check
          </button>
        </div>

        <div className="grid flex-1 gap-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <main className="flex min-h-0 flex-col gap-4">
            <section>
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="text-2xl font-semibold">{currentStage}</h1>
                {(setup.loading || setup.running) && (
                  <span className="loading loading-spinner loading-sm" />
                )}
                {status === "ready" && (
                  <span className="badge badge-success gap-1">
                    <IconCheck />
                    Ready
                  </span>
                )}
                {(status === "failed" || isBlocked) && (
                  <span className="badge badge-error gap-1">
                    <IconOctagonAlert />
                    {status}
                  </span>
                )}
              </div>
            </section>

            <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <div className="rounded border border-base-content/10 bg-base-200 p-3">
                <div className="text-xs uppercase text-base-content/50">Platform</div>
                <div className="font-mono text-sm">
                  {detail ? `${detail.platform}/${detail.architecture}` : "checking"}
                </div>
              </div>
              <div className="rounded border border-base-content/10 bg-base-200 p-3">
                <div className="text-xs uppercase text-base-content/50">App</div>
                <div className="font-mono text-sm">{detail?.appVersion ?? "checking"}</div>
              </div>
              <div className="rounded border border-base-content/10 bg-base-200 p-3">
                <div className="text-xs uppercase text-base-content/50">Target</div>
                <div className="font-mono text-sm">{detail?.commandTarget ?? "checking"}</div>
              </div>
              <div className="rounded border border-base-content/10 bg-base-200 p-3">
                <div className="text-xs uppercase text-base-content/50">Docker</div>
                <div className="font-mono text-sm">{detail?.dockerStatus ?? "not verified"}</div>
              </div>
              <div className="rounded border border-base-content/10 bg-base-200 p-3">
                <div className="text-xs uppercase text-base-content/50">CLI</div>
                <div className="font-mono text-sm">{detail?.cliVersion ?? "not installed"}</div>
              </div>
            </section>

            {(setup.error || detail?.lastError) && (
              <section className="rounded border border-error/40 bg-error/10 p-3">
                <div className="flex items-start gap-2">
                  <IconOctagonAlert className="mt-1 shrink-0 text-error" />
                  <div>
                    <div className="font-semibold">Setup needs attention</div>
                    <div className="text-sm text-base-content/80">
                      {setup.error ?? detail?.lastError}
                    </div>
                    {detail?.remediationKind && (
                      <div className="mt-1 font-mono text-xs text-base-content/60">
                        {detail.remediationKind}
                      </div>
                    )}
                  </div>
                </div>
              </section>
            )}

            <section className="flex min-h-0 flex-1 flex-col">
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-sm font-semibold uppercase text-base-content/60">
                  Setup Log
                </h2>
                <div className="flex gap-2">
                  {setup.running ? (
                    <button className="btn btn-sm btn-outline" onClick={setup.cancelSetup}>
                      <IconStop />
                      Cancel
                    </button>
                  ) : (
                    <button
                      className="btn btn-sm btn-primary"
                      disabled={!canRun}
                      onClick={setup.runRecommendedSetupAction}
                    >
                      <IconPlay />
                      {setupActionLabel(status, detail?.remediationKind)}
                    </button>
                  )}
                </div>
              </div>
              <div
                ref={outputRef}
                className="min-h-72 flex-1 overflow-auto rounded bg-neutral p-3 font-mono text-sm text-neutral-content"
              >
                {setup.terminalOutput.length > 0 ? (
                  <pre className="whitespace-pre-wrap break-words">{setup.terminalOutput}</pre>
                ) : setup.logs.length === 0 ? (
                  <div className="text-neutral-content/50">
                    Setup output will appear here.
                  </div>
                ) : (
                  setup.logs.map((entry, index) => (
                    <div
                      key={`${entry.stage}-${index}`}
                      className={entry.stream === "stderr" ? "text-error-content" : ""}
                    >
                      <span className="text-neutral-content/40">[{entry.stage}] </span>
                      {entry.line}
                    </div>
                  ))
                )}
              </div>
              <form className="mt-2 flex gap-2" onSubmit={sendInstallerInput}>
                <input
                  className="input input-sm input-bordered min-w-0 flex-1 font-mono"
                  type="password"
                  value={installerInput}
                  placeholder="installer input"
                  autoComplete="off"
                  disabled={!setup.running}
                  onChange={(event) => setInstallerInput(event.target.value)}
                />
                <button
                  className="btn btn-sm btn-outline"
                  type="submit"
                  disabled={!setup.running || installerInput.length === 0}
                >
                  <IconPlay />
                  Send
                </button>
              </form>
            </section>
          </main>

          <aside className="space-y-4">
            <section className="rounded border border-base-content/10 bg-base-200 p-4">
              <h2 className="mb-2 font-semibold">First-run stack</h2>
              <div className="flex flex-wrap gap-2">
                {(detail?.firstRunStackServiceList.length
                  ? detail.firstRunStackServiceList
                  : ["llamacpp", "webui"]
                ).map((service) => (
                  <span key={service} className="badge badge-outline">
                    {service}
                  </span>
                ))}
              </div>
              <div className="mt-3 break-all font-mono text-xs text-base-content/60">
                {detail?.selectedSmallModel}
              </div>
            </section>

            <section className="rounded border border-base-content/10 bg-base-200 p-4">
              <h2 className="mb-2 font-semibold">Verification</h2>
              <div className="space-y-2 text-sm">
                <div>{detail?.doctorSummary ?? "Harbor doctor has not run yet."}</div>
                <div>
                  {detail?.inferenceVerificationResult ??
                    "llama.cpp inference has not been verified yet."}
                </div>
              </div>
              {detail?.openWebuiUrl && (
                <button
                  className="btn btn-sm btn-outline mt-4 w-full"
                  onClick={setup.openWebui}
                  disabled={setup.running}
                >
                  <IconExternalLink />
                  Open WebUI
                </button>
              )}
            </section>

            <section className="rounded border border-base-content/10 bg-base-200 p-4">
              <div className="mb-2 flex items-center justify-between gap-3">
                <h2 className="font-semibold">Manual recovery</h2>
                <button
                  type="button"
                  className="btn btn-xs btn-ghost"
                  onClick={() => navigator.clipboard.writeText(manualCommand)}
                >
                  <IconCopy />
                  Copy
                </button>
              </div>
              <div className="break-all rounded bg-base-300 p-2 font-mono text-xs">
                {manualCommand}
              </div>
            </section>
          </aside>
        </div>
      </div>
    </div>
  );
};
