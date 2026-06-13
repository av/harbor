import { FC, FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import {
  IconBadgeCheck,
  IconExternalLink,
  IconEye,
  IconEyeOff,
  IconOctagonAlert,
  IconPlay,
  IconRotateCW,
  IconStop,
} from "../Icons";
import { runOpen } from "../useOpen";
import { toasted } from "../utils";
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
    title: "Can't install automatically",
    message:
      "Harbor needs additional software that isn't available on this computer.",
    actions: [
      "See the message below for what's needed",
      "After installing it, click Redetect",
    ],
    level: "warning",
  },
  "refresh-required": {
    title: "Almost done",
    message:
      "Harbor was installed, but it can't fully connect to Docker yet.",
    actions: [
      "Log out of your computer and log back in, then reopen Harbor",
      "If that doesn't help, try restarting your computer",
      "Click Redetect below to check again",
    ],
    level: "info",
  },
  failed: {
    title: "Installation didn't finish",
    message: "Something went wrong during setup.",
    actions: [
      "Make sure you're connected to the internet and click Retry",
      "If it keeps failing, visit github.com/av/harbor/issues for help",
    ],
    level: "error",
  },
  cancelled: {
    title: "Installation cancelled",
    message: "You stopped the installation before it completed.",
    actions: ["Click Retry when you're ready to try again"],
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
  "refresh-required": "Almost done",
  "not-installed": "Not installed",
};

const INSTALLABLE_STATUSES = new Set(["not-installed", "failed", "cancelled"]);

const alertClass: Record<GuidanceLevel, string> = {
  warning: "alert-warning",
  info: "alert-info",
  error: "alert-error",
};

const GuidanceAlert: FC<{ guidance: StateGuidance; className?: string }> = ({
  guidance,
  className,
}) => (
  <div className={`alert ${alertClass[guidance.level]} text-left ${className ?? ""}`}>
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
);

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
    onClick={() => toasted({
      action: () => runOpen([DOCS_URL]),
      error: "Failed to open documentation",
    })}
  >
    Documentation <IconExternalLink className="h-3 w-3" />
  </button>
);

export const HarborSetupGate: FC<{ children: ReactNode }> = ({ children }) => {
  const setup = useHarborSetup();
  const outputRef = useRef<HTMLDivElement>(null);
  const [input, setInput] = useState("");
  const [showInput, setShowInput] = useState(false);

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
    INSTALLABLE_STATUSES.has(status);
  const isIdle = !setup.running && !setup.terminalOutput;
  const guidance = stateGuidance[status];
  const displayError = setup.error ?? setup.detail?.lastError;

  const sendInput = async (e: FormEvent) => {
    e.preventDefault();
    if (!setup.running || !input) return;
    try {
      await setup.writeSetupInput(input + "\n");
      setInput("");
    } catch {
      // writeSetupInput already called setError; keep input so the user
      // doesn't have to retype their password after a transient failure.
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
              <GuidanceAlert guidance={guidance} className="max-w-lg" />
            )}

            {displayError && (
              <p className={`max-w-md text-center text-sm ${status === "not-installed" ? "text-base-content/60" : "text-error"}`}>
                {displayError}
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
          <GuidanceAlert guidance={guidance} />
        )}

        {displayError && !setup.running && (
          <div className="rounded-box border border-error/20 bg-error/5 px-4 py-2 text-sm text-error">
            {displayError}
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

        {/* Input for installer prompts */}
        {setup.running && (
          <form className="flex gap-2" onSubmit={sendInput}>
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <div className="flex gap-1">
                <input
                  className="input input-sm input-bordered min-w-0 flex-1 font-mono"
                  type={showInput ? "text" : "password"}
                  value={input}
                  placeholder="Respond to installer prompt"
                  autoComplete="off"
                  onChange={(e) => setInput(e.target.value)}
                />
                <button
                  type="button"
                  className="btn btn-sm btn-ghost"
                  onClick={() => setShowInput((v) => !v)}
                  tabIndex={-1}
                  aria-label={showInput ? "Hide input" : "Show input"}
                >
                  {showInput ? <IconEyeOff /> : <IconEye />}
                </button>
              </div>
              <span className="text-xs text-base-content/50">
                Sent to the installer — e.g. your password when prompted, or answers to other prompts
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
