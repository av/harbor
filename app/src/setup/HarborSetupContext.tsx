import { listen } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";
import * as harborLocalStorage from "../localStorage";
import {
  createContext,
  FC,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

export type HarborSetupStatus =
  | "checking-platform"
  | "checking-prerequisites"
  | "installing-prerequisites"
  | "checking-cli"
  | "installing-cli"
  | "refresh-required"
  | "verifying-cli"
  | "configuring-first-run-stack"
  | "starting-first-run-stack"
  | "verifying-inference"
  | "ready"
  | "blocked"
  | "failed"
  | "cancelled";

export interface HarborSetupDetail {
  status: HarborSetupStatus;
  platform: string;
  architecture: string;
  appVersion: string;
  commandTarget: string;
  installTarget: string;
  cliVersion?: string | null;
  dockerStatus?: string | null;
  dockerComposeStatus?: string | null;
  doctorSummary?: string | null;
  firstRunStackServiceList: string[];
  runningServiceList: string[];
  openWebuiUrl?: string | null;
  selectedSmallModel: string;
  inferenceVerificationResult?: string | null;
  lastError?: string | null;
  remediationKind?: string | null;
  running: boolean;
}

export interface HarborSetupLogEntry {
  stage: string;
  stream: string;
  line: string;
}

interface HarborSetupContextValue {
  detail: HarborSetupDetail | null;
  loading: boolean;
  running: boolean;
  logs: HarborSetupLogEntry[];
  terminalOutput: string;
  error: string | null;
  ready: boolean;
  redetect: () => Promise<void>;
  startSetup: () => Promise<void>;
  runRecommendedSetupAction: () => Promise<void>;
  writeSetupInput: (data: string) => Promise<void>;
  startFirstRunStack: () => Promise<void>;
  cancelSetup: () => Promise<void>;
  openWebui: () => Promise<void>;
}

const HarborSetupContext = createContext<HarborSetupContextValue | null>(null);
const SETUP_STORAGE_KEY = "harborSetupSnapshot";
const MAX_SETUP_LOGS = 1000;
const MAX_SETUP_TERMINAL_OUTPUT = 200000;

const CHECKING_DETAIL: HarborSetupDetail = {
  status: "checking-platform",
  platform: "unknown",
  architecture: "unknown",
  appVersion: "unknown",
  commandTarget: "unknown",
  installTarget: "unknown",
  firstRunStackServiceList: [],
  runningServiceList: [],
  selectedSmallModel: "",
  running: false,
};

const SETUP_STATUSES: HarborSetupStatus[] = [
  "checking-platform",
  "checking-prerequisites",
  "installing-prerequisites",
  "checking-cli",
  "installing-cli",
  "refresh-required",
  "verifying-cli",
  "configuring-first-run-stack",
  "starting-first-run-stack",
  "verifying-inference",
  "ready",
  "blocked",
  "failed",
  "cancelled",
];

interface HarborSetupSnapshot {
  detail: HarborSetupDetail | null;
  logs: HarborSetupLogEntry[];
  terminalOutput: string;
  error: string | null;
  updatedAt: string | null;
}

const EMPTY_SETUP_SNAPSHOT: HarborSetupSnapshot = {
  detail: CHECKING_DETAIL,
  logs: [],
  terminalOutput: "",
  error: null,
  updatedAt: null,
};

function normalizeSetupDetail(detail: HarborSetupDetail | null | undefined) {
  return detail ? { ...CHECKING_DETAIL, ...detail, running: false } : CHECKING_DETAIL;
}

function readStoredSetupSnapshot(): HarborSetupSnapshot {
  const snapshot = harborLocalStorage.readLocalStorage<HarborSetupSnapshot>(
    SETUP_STORAGE_KEY,
    EMPTY_SETUP_SNAPSHOT,
  );

  return {
    detail: normalizeSetupDetail(snapshot.detail),
    logs: Array.isArray(snapshot.logs) ? snapshot.logs.slice(-MAX_SETUP_LOGS) : [],
    terminalOutput:
      typeof snapshot.terminalOutput === "string"
        ? snapshot.terminalOutput.slice(-MAX_SETUP_TERMINAL_OUTPUT)
        : "",
    error: snapshot.error ?? null,
    updatedAt: snapshot.updatedAt ?? null,
  };
}

function writeStoredSetupSnapshot(snapshot: HarborSetupSnapshot) {
  harborLocalStorage.writeLocalStorage(SETUP_STORAGE_KEY, {
    ...snapshot,
    detail: snapshot.detail ? { ...snapshot.detail, running: false } : null,
    logs: snapshot.logs.slice(-MAX_SETUP_LOGS),
    terminalOutput: snapshot.terminalOutput.slice(-MAX_SETUP_TERMINAL_OUTPUT),
    updatedAt: new Date().toISOString(),
  });
}

function asErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

function setupStatusFromError(message: string): HarborSetupStatus | null {
  const match = message.match(/HARBOR_SETUP_STATUS=([a-z-]+)/);
  if (!match) return null;

  const status = match[1] as HarborSetupStatus;
  return SETUP_STATUSES.includes(status) ? status : null;
}

function cleanSetupError(message: string) {
  return message.replace(/^HARBOR_SETUP_STATUS=[^;]+;\s*/, "");
}

function shouldPreserveErrorStatus(status: HarborSetupStatus) {
  return (
    status === "failed" ||
    status === "blocked" ||
    status === "cancelled" ||
    status === "refresh-required"
  );
}

function isTerminalSetupStatus(status: HarborSetupStatus) {
  return (
    status === "ready" ||
    status === "blocked" ||
    status === "failed" ||
    status === "cancelled" ||
    status === "refresh-required"
  );
}

function remediationKindFromError(message: string): string {
  if (message.includes("Ubuntu WSL installation started")) return "missing-wsl-distro";
  if (message.includes("WSL installation started")) return "missing-wsl";
  if (message.includes("not a WSL2 distro")) return "missing-wsl-distro";
  if (message.includes("Docker Desktop installation completed")) return "missing-docker-desktop";
  if (message.includes("accept required first-run prompts")) return "restart-required";
  if (message.includes("Docker Desktop did not become reachable")) return "wsl-docker-integration";
  if (message.includes("enable WSL integration")) return "wsl-docker-integration";
  if (message.includes("Docker Desktop is not reachable inside WSL")) {
    return "wsl-docker-integration";
  }
  if (
    message.includes("Docker daemon") ||
    message.includes("Docker is not reachable") ||
    message.includes("Start Docker Desktop")
  ) {
    return "docker-daemon-unreachable";
  }
  if (message.includes("webui-backend-config-failed")) {
    return "webui-backend-config-failed";
  }
  if (message.includes("configuring-first-run-stack")) return "stack-config-failed";
  if (message.includes("starting-first-run-stack")) return "stack-start-failed";
  if (message.includes("verifying-inference")) return "llamacpp-inference-failed";
  if (message.includes("verifying-cli")) return "verification-failed";
  return "installer-failed";
}

function isFirstRunStackRemediation(remediationKind?: string | null) {
  return (
    remediationKind === "stack-config-failed" ||
    remediationKind === "stack-start-failed" ||
    remediationKind === "webui-health-failed" ||
    remediationKind === "webui-backend-config-failed" ||
    remediationKind === "llamacpp-inference-failed"
  );
}

export const HarborSetupProvider: FC<{ children: ReactNode }> = ({ children }) => {
  const [initialSnapshot] = useState(readStoredSetupSnapshot);
  const [detail, setDetail] = useState<HarborSetupDetail | null>(initialSnapshot.detail);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [logs, setLogs] = useState<HarborSetupLogEntry[]>(initialSnapshot.logs);
  const [terminalOutput, setTerminalOutput] = useState(initialSnapshot.terminalOutput);
  const [error, setError] = useState<string | null>(initialSnapshot.error);

  useEffect(() => {
    const unlisteners: Array<() => void> = [];

    listen<HarborSetupLogEntry>("harbor-setup-log", (event) => {
      setLogs((prev) => {
        const next = [...prev, event.payload];
        return next.length > MAX_SETUP_LOGS ? next.slice(next.length - MAX_SETUP_LOGS) : next;
      });
    }).then((unlisten) => unlisteners.push(unlisten));

    listen<{ data: string }>("harbor-setup-terminal-output", (event) => {
      setTerminalOutput((prev) => {
        const next = `${prev}${event.payload.data}`;
        return next.length > MAX_SETUP_TERMINAL_OUTPUT
          ? next.slice(next.length - MAX_SETUP_TERMINAL_OUTPUT)
          : next;
      });
    }).then((unlisten) => unlisteners.push(unlisten));

    listen<{ status: HarborSetupStatus }>("harbor-setup-status", (event) => {
      setDetail((prev) => ({
        ...(prev ?? CHECKING_DETAIL),
        status: event.payload.status,
        running: !isTerminalSetupStatus(event.payload.status),
      }));
    }).then((unlisten) => unlisteners.push(unlisten));

    return () => {
      unlisteners.forEach((unlisten) => unlisten());
    };
  }, []);

  useEffect(() => {
    writeStoredSetupSnapshot({
      detail,
      logs,
      terminalOutput,
      error,
      updatedAt: initialSnapshot.updatedAt,
    });
  }, [detail, logs, terminalOutput, error, initialSnapshot.updatedAt]);

  const redetect = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await invoke<HarborSetupDetail>("detect_harbor_setup");
      setDetail(next);
      setRunning(next.running);
    } catch (e) {
      setError(asErrorMessage(e));
      setDetail((prev) => ({
        ...(prev ?? CHECKING_DETAIL),
        status: "failed",
        lastError: asErrorMessage(e),
      }));
    } finally {
      setLoading(false);
    }
  }, []);

  const startSetup = useCallback(async () => {
    setRunning(true);
    setError(null);
    setLogs([]);
    setTerminalOutput("");
    let shouldRedetect = true;
    try {
      const next = await invoke<HarborSetupDetail>("start_harbor_setup");
      setDetail(next);
      shouldRedetect = false;
    } catch (e) {
      const rawMessage = asErrorMessage(e);
      const status = setupStatusFromError(rawMessage) ?? "failed";
      const message = cleanSetupError(rawMessage);
      shouldRedetect = !shouldPreserveErrorStatus(status);
      setError(message);
      setDetail((prev) => ({
        ...(prev ?? CHECKING_DETAIL),
        status,
        lastError: message,
        remediationKind: remediationKindFromError(message),
      }));
    } finally {
      setRunning(false);
      if (shouldRedetect) redetect();
    }
  }, [redetect]);

  const startFirstRunStack = useCallback(async () => {
    setRunning(true);
    setError(null);
    setLogs([]);
    setTerminalOutput("");
    let shouldRedetect = true;
    try {
      await invoke("configure_first_run_stack");
      await invoke("start_first_run_stack");
      await invoke("verify_first_run_stack");
      shouldRedetect = false;
    } catch (e) {
      const rawMessage = asErrorMessage(e);
      const status = setupStatusFromError(rawMessage) ?? "failed";
      const message = cleanSetupError(rawMessage);
      shouldRedetect = !shouldPreserveErrorStatus(status);
      setError(message);
      setDetail((prev) => ({
        ...(prev ?? CHECKING_DETAIL),
        status,
        lastError: message,
        remediationKind: remediationKindFromError(message),
      }));
    } finally {
      setRunning(false);
      if (shouldRedetect) redetect();
    }
  }, [redetect]);

  const writeSetupInput = useCallback(async (data: string) => {
    setError(null);
    try {
      await invoke("write_harbor_setup_input", { data });
    } catch (e) {
      setError(asErrorMessage(e));
      throw e;
    }
  }, []);

  const cancelSetup = useCallback(async () => {
    try {
      await invoke("cancel_harbor_setup");
      setDetail((prev) => ({
        ...(prev ?? CHECKING_DETAIL),
        status: "cancelled",
        running: false,
      }));
    } catch (e) {
      setError(asErrorMessage(e));
    } finally {
      setRunning(false);
    }
  }, []);

  const openWebui = useCallback(async () => {
    setError(null);
    try {
      await invoke("open_webui");
    } catch (e) {
      setError(asErrorMessage(e));
    }
  }, []);

  const runRecommendedSetupAction = useCallback(async () => {
    const status = detail?.status ?? "checking-platform";
    const remediationKind = detail?.remediationKind;
    if (status === "blocked" && remediationKind === "docker-daemon-unreachable") {
      return startSetup();
    }
    if (isFirstRunStackRemediation(remediationKind)) {
      return startFirstRunStack();
    }
    if (status === "blocked" || status === "refresh-required") {
      return redetect();
    }
    if (
      status === "configuring-first-run-stack" ||
      status === "starting-first-run-stack" ||
      status === "verifying-inference"
    ) {
      return startFirstRunStack();
    }
    return startSetup();
  }, [detail?.remediationKind, detail?.status, redetect, startFirstRunStack, startSetup]);

  useEffect(() => {
    redetect();
  }, [redetect]);

  const value = useMemo<HarborSetupContextValue>(
    () => ({
      detail,
      loading,
      running,
      logs,
      terminalOutput,
      error,
      ready: !loading && detail?.status === "ready",
      redetect,
      startSetup,
      runRecommendedSetupAction,
      writeSetupInput,
      startFirstRunStack,
      cancelSetup,
      openWebui,
    }),
    [detail, loading, running, logs, terminalOutput, error, redetect, startSetup, runRecommendedSetupAction, writeSetupInput, startFirstRunStack, cancelSetup, openWebui],
  );

  return (
    <HarborSetupContext.Provider value={value}>
      {children}
    </HarborSetupContext.Provider>
  );
};

export function useHarborSetup() {
  const value = useContext(HarborSetupContext);
  if (!value) {
    throw new Error("useHarborSetup must be used within HarborSetupProvider");
  }
  return value;
}
