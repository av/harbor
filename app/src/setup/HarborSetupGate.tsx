import { FC, FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import {
  IconBadgeCheck,
  IconExternalLink,
  IconOctagonAlert,
  IconPlay,
  IconRotateCW,
  IconStop,
} from "../Icons";
import { runOpen } from "../useOpen";
import { useHarborSetup } from "./HarborSetupContext";

const DOCS_URL = "https://github.com/av/harbor";

const SETUP_STEPS = [
  { key: "checking-platform", label: "Check" },
  { key: "checking-prerequisites", label: "Prerequisites" },
  { key: "installing-prerequisites", label: "Install deps" },
  { key: "installing-cli", label: "Install CLI" },
  { key: "linking-cli", label: "Link CLI" },
  { key: "verifying-cli", label: "Verify" },
] as const;

const STEP_ORDER = SETUP_STEPS.map((s) => s.key);

type GuidanceLevel = "warning" | "info" | "error";

interface StateGuidance {
  title: string;
  message: string;
  actions: string[];
  level: GuidanceLevel;
}

const stateGuidance: Record<string, StateGuidance> = {
  blocked: {
    title: "Installation blocked",
    message:
      "A prerequisite is missing that prevents Harbor from being installed.",
    actions: [
      "Check the error details below for the specific issue",
      "On macOS: install Docker Desktop from docker.com/products/docker-desktop",
      "On Linux: ensure Docker Engine and a supported package manager (apt, dnf, pacman, apk, or zypper) are available",
      "On Windows: enable WSL2 and install a supported Linux distro (Ubuntu, Debian, Fedora, openSUSE, Kali, or Arch)",
      "After fixing the issue, click Redetect to try again",
    ],
    level: "warning",
  },
  "refresh-required": {
    title: "Almost there -- restart needed",
    message:
      "Harbor CLI is installed, but your session needs refreshing to access Docker.",
    actions: [
      "Close and reopen the Harbor app",
      "On Linux, you may need to log out and back in to pick up docker group membership",
      "Alternatively, open a terminal and run: newgrp docker",
    ],
    level: "info",
  },
  failed: {
    title: "Installation failed",
    message: "The setup process encountered an error it could not recover from.",
    actions: [
      "Expand the terminal output above to see the specific error",
      "Check your internet connection (Harbor downloads ~50 MB during install)",
      "If a package install failed, try installing Docker and git manually, then click Retry",
      "If the problem persists, visit github.com/av/harbor/issues for help",
    ],
    level: "error",
  },
  cancelled: {
    title: "Installation cancelled",
    message: "You stopped the installation before it completed.",
    actions: ["Click Retry to start again when you are ready"],
    level: "info",
  },
};

const statusLabels: Record<string, string> = {
  starting: "Starting installation",
  "checking-platform": "Checking platform",
  "checking-prerequisites": "Checking prerequisites",
  "installing-prerequisites": "Installing prerequisites",
  "installing-cli": "Installing Harbor CLI",
  "linking-cli": "Linking CLI to PATH",
  "verifying-cli": "Verifying installation",
  ready: "Ready",
  blocked: "Blocked",
  failed: "Setup failed",
  cancelled: "Cancelled",
  "refresh-required": "Restart required",
  "not-installed": "Not installed",
};

const alertClass: Record<GuidanceLevel, string> = {
  warning: "alert-warning",
  info: "alert-info",
  error: "alert-error",
};

function stepState(
  stepKey: string,
  currentStatus: string,
): "done" | "active" | "pending" {
  // Terminal success — all steps completed.
  if (currentStatus === "ready") return "done";
  const currentIndex = STEP_ORDER.indexOf(currentStatus as (typeof STEP_ORDER)[number]);
  const stepIndex = STEP_ORDER.indexOf(stepKey as (typeof STEP_ORDER)[number]);
  // For statuses not in STEP_ORDER (failed, blocked, cancelled, etc.),
  // show steps as pending so the indicator doesn't misleadingly advance.
  if (currentIndex < 0) return "pending";
  if (stepIndex < currentIndex) return "done";
  if (stepIndex === currentIndex) return "active";
  return "pending";
}

const DocsLink: FC = () => (
  <button
    className="link link-hover inline-flex items-center gap-1 text-sm text-base-content/50"
    onClick={() => runOpen([DOCS_URL])}
  >
    Documentation <IconExternalLink className="h-3 w-3" />
  </button>
);

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

  // ── Success screen ────────────────────────────────
  if (setup.justInstalled) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4 bg-base-100 text-base-content">
        <IconBadgeCheck className="h-16 w-16 text-success" />
        <h2 className="text-2xl font-bold">Harbor is ready</h2>
        {setup.detail?.cliVersion && (
          <p className="text-base-content/60 text-sm">
            CLI version: {setup.detail.cliVersion}
          </p>
        )}
        <button
          className="btn btn-primary"
          onClick={setup.dismissSuccess}
        >
          Get Started
        </button>
      </div>
    );
  }

  const status = setup.detail?.status ?? "checking";
  const canInstall =
    !setup.loading &&
    !setup.running &&
    (status === "not-installed" ||
      status === "failed" ||
      status === "cancelled");
  const isIdle = !setup.running && !setup.terminalOutput;
  const guidance = stateGuidance[status];

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

  // ── Pre-install welcome screen ────────────────────
  if (isIdle) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-6 bg-base-100 px-6 text-base-content">
        {setup.loading ? (
          <span className="loading loading-spinner loading-lg" />
        ) : (
          <>
            <h1 className="text-5xl font-bold tracking-tight">Harbor</h1>

            {!guidance && (
              <p className="max-w-sm text-center text-base-content/60">
                Harbor manages AI services through Docker.
                <br />
                The CLI is needed to control services locally.
              </p>
            )}

            {guidance && (
              <div
                className={`alert ${alertClass[guidance.level]} max-w-lg text-left`}
              >
                <IconOctagonAlert className="h-5 w-5 shrink-0" />
                <div>
                  <h3 className="font-bold">{guidance.title}</h3>
                  <p className="text-sm">{guidance.message}</p>
                  <ul className="mt-2 list-disc pl-4 text-sm">
                    {guidance.actions.map((a) => (
                      <li key={a}>{a}</li>
                    ))}
                  </ul>
                </div>
              </div>
            )}

            {(setup.error || setup.detail?.lastError) && (
              <p className="max-w-md text-center text-sm text-error">
                {setup.error ?? setup.detail?.lastError}
              </p>
            )}

            {canInstall && !guidance && (
              <div className="collapse collapse-arrow max-w-lg bg-base-200">
                <input type="checkbox" />
                <div className="collapse-title text-sm font-medium">
                  What will be installed?
                </div>
                <div className="collapse-content text-sm text-base-content/70">
                  <ul className="list-disc space-y-1 pl-4">
                    <li>
                      Check and install prerequisites (Docker, git, curl) via
                      your system package manager
                    </li>
                    <li>
                      May prompt for your system password (sudo) to install
                      packages
                    </li>
                    <li>Clone the Harbor repository (~50 MB)</li>
                    <li>
                      Link the <code>harbor</code> command to your PATH
                    </li>
                  </ul>
                </div>
              </div>
            )}

            <div className="flex gap-3">
              {canInstall && (
                <button
                  className="btn btn-primary"
                  onClick={setup.startSetup}
                >
                  {status === "failed" || status === "cancelled"
                    ? "Retry Installation"
                    : "Install Harbor"}
                </button>
              )}
              {(guidance || status === "not-installed" || setup.error) && (
                <button
                  className="btn btn-ghost btn-sm self-center"
                  onClick={setup.redetect}
                >
                  <IconRotateCW className="h-4 w-4" /> Redetect
                </button>
              )}
            </div>

            <div className="flex flex-col items-center gap-2 pt-4 text-base-content/40">
              {status === "not-installed" && (
                <span className="text-xs">
                  Already have Harbor installed? Click Redetect above.
                </span>
              )}
              <DocsLink />
            </div>
          </>
        )}
      </div>
    );
  }

  // ── During-install / post-install with output ─────
  return (
    <div className="flex h-screen flex-col bg-base-100 text-base-content">
      <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 overflow-hidden px-4 py-6">
        {/* Step indicator */}
        <ul className="steps steps-horizontal w-full text-xs">
          {SETUP_STEPS.map((step) => {
            const state = stepState(step.key, status);
            return (
              <li
                key={step.key}
                className={`step ${state !== "pending" ? "step-primary" : ""}`}
              >
                {step.label}
              </li>
            );
          })}
        </ul>

        {/* Status + progress */}
        <div className="flex flex-col items-center gap-2">
          <div className="flex items-center gap-2 text-sm text-base-content/60">
            {setup.running && (
              <span className="loading loading-spinner loading-xs" />
            )}
            <span>{statusLabels[status] ?? status}</span>
          </div>
          {setup.running && (
            <progress className="progress progress-primary w-full" />
          )}
        </div>

        {/* Guidance alert for terminal states */}
        {!setup.running && guidance && (
          <div
            className={`alert ${alertClass[guidance.level]} text-left`}
          >
            <IconOctagonAlert className="h-5 w-5 shrink-0" />
            <div>
              <h3 className="font-bold">{guidance.title}</h3>
              <p className="text-sm">{guidance.message}</p>
              <ul className="mt-2 list-disc pl-4 text-sm">
                {guidance.actions.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </div>
          </div>
        )}

        {(setup.error || setup.detail?.lastError) && !setup.running && (
          <div className="rounded-box border border-error/20 bg-error/5 px-4 py-2 text-sm text-error">
            {setup.error ?? setup.detail?.lastError}
          </div>
        )}

        {/* Terminal output collapse */}
        <div className="collapse collapse-arrow min-h-0 flex-1 bg-base-200">
          <input type="checkbox" defaultChecked />
          <div className="collapse-title text-sm text-base-content/70">
            Terminal output
          </div>
          <div
            ref={outputRef}
            className="collapse-content !min-h-0 overflow-y-auto font-mono text-sm text-base-content"
          >
            <pre className="whitespace-pre-wrap break-words">
              {setup.terminalOutput}
            </pre>
          </div>
        </div>

        {/* Input for sudo / installer prompts */}
        {setup.running && (
          <form className="flex gap-2" onSubmit={sendInput}>
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <input
                className="input input-sm input-bordered min-w-0 font-mono"
                type="password"
                value={input}
                placeholder="sudo password"
                autoComplete="off"
                onChange={(e) => setInput(e.target.value)}
              />
              <span className="text-xs text-base-content/50">
                Your system password — needed to install system packages
              </span>
            </div>
            <button
              className="btn btn-sm btn-ghost self-start"
              type="submit"
              disabled={!input}
            >
              Send
            </button>
          </form>
        )}

        {/* Action buttons */}
        <div className="flex items-center justify-center gap-3">
          {setup.running && (
            <button
              className="btn btn-sm btn-outline btn-error"
              onClick={setup.cancelSetup}
            >
              <IconStop /> Cancel Installation
            </button>
          )}
          {!setup.running && canInstall && (
            <button
              className="btn btn-sm btn-primary"
              onClick={setup.startSetup}
            >
              <IconPlay /> Retry
            </button>
          )}
          {!setup.running && (
            <button
              className="btn btn-sm btn-ghost"
              onClick={setup.redetect}
            >
              <IconRotateCW className="h-4 w-4" /> Redetect
            </button>
          )}
        </div>

        {/* Footer help link */}
        {!setup.running && (
          <div className="flex justify-center pb-2">
            <DocsLink />
          </div>
        )}
      </div>
    </div>
  );
};
