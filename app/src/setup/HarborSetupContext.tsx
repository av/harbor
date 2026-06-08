import { listen } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";
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

export interface HarborSetupDetail {
  status: string;
  platform: string;
  cliVersion: string | null;
  lastError: string | null;
  running: boolean;
}

interface HarborSetupContextValue {
  detail: HarborSetupDetail | null;
  loading: boolean;
  running: boolean;
  terminalOutput: string;
  error: string | null;
  ready: boolean;
  justInstalled: boolean;
  redetect: () => Promise<void>;
  startSetup: () => Promise<void>;
  writeSetupInput: (data: string) => Promise<void>;
  cancelSetup: () => Promise<void>;
  dismissSuccess: () => void;
}

const HarborSetupContext = createContext<HarborSetupContextValue | null>(null);
const MAX_TERMINAL_OUTPUT = 200000;

const DEFAULT_DETAIL: HarborSetupDetail = {
  status: "checking",
  platform: "unknown",
  cliVersion: null,
  lastError: null,
  running: false,
};

const TERMINAL_STATUSES = new Set([
  "ready",
  "blocked",
  "failed",
  "cancelled",
  "refresh-required",
  "not-installed",
]);

export const HarborSetupProvider: FC<{ children: ReactNode }> = ({ children }) => {
  const [detail, setDetail] = useState<HarborSetupDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [terminalOutput, setTerminalOutput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [justInstalled, setJustInstalled] = useState(false);

  const redetect = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await invoke<HarborSetupDetail>("detect_harbor_setup");
      if (import.meta.env.VITE_FORCE_SETUP && next.status === "ready") {
        next.status = "not-installed";
      }
      setDetail(next);
      setRunning(next.running);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const unlisteners: Array<() => void> = [];

    async function init() {
      const [unlistenOutput, unlistenStatus, unlistenComplete] = await Promise.all([
        listen<{ data: string }>("harbor-setup-terminal-output", (event) => {
          setTerminalOutput((prev) => {
            const next = prev + event.payload.data;
            return next.length > MAX_TERMINAL_OUTPUT
              ? next.slice(next.length - MAX_TERMINAL_OUTPUT)
              : next;
          });
        }),
        listen<{ status: string }>("harbor-setup-status", (event) => {
          // Ignore "ready" here — the complete event handles it.
          // Processing "ready" in this listener would momentarily set
          // detail.status="ready" + running=false before justInstalled
          // is set by the complete handler, making the setup gate flash
          // the main app for one render frame.
          if (event.payload.status === "ready") return;
          const isTerminal = TERMINAL_STATUSES.has(event.payload.status);
          setDetail((prev) => ({
            ...(prev ?? DEFAULT_DETAIL),
            status: event.payload.status,
            running: !isTerminal,
          }));
          // Keep the top-level running state in sync with detail.running.
          // Without this, a redetect() during install that returns running:true
          // would not be reflected in the component-level `running` state.
          setRunning(!isTerminal);
        }),
        listen<{ detail: HarborSetupDetail; error: string | null }>(
          "harbor-setup-complete",
          (event) => {
            setDetail(event.payload.detail);
            setRunning(false);
            if (event.payload.error) {
              const raw = event.payload.error;
              const message = raw.replace(/^HARBOR_SETUP_STATUS=[^;]+;\s*/, "");
              setError(message);
            }
            if (event.payload.detail.status === "ready") {
              setJustInstalled(true);
            } else if (!event.payload.error) {
              redetect();
            }
          },
        ),
      ]);

      if (cancelled) {
        unlistenOutput();
        unlistenStatus();
        unlistenComplete();
        return;
      }

      unlisteners.push(unlistenOutput, unlistenStatus, unlistenComplete);
      redetect();
    }

    init();
    return () => {
      cancelled = true;
      unlisteners.forEach((fn) => fn());
    };
  }, [redetect]);

  const startSetup = useCallback(async () => {
    setRunning(true);
    setError(null);
    setTerminalOutput("");
    setDetail((prev) => ({
      ...(prev ?? DEFAULT_DETAIL),
      status: "starting",
      running: true,
      lastError: null,
    }));
    try {
      await invoke("start_harbor_setup");
    } catch (e) {
      const rawMessage = e instanceof Error ? e.message : String(e);
      setError(rawMessage);
      setRunning(false);
      setDetail((prev) => ({
        ...(prev ?? DEFAULT_DETAIL),
        status: "failed",
        running: false,
        lastError: rawMessage,
      }));
    }
  }, []);

  const writeSetupInput = useCallback(async (data: string) => {
    try {
      await invoke("write_harbor_setup_input", { data });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const cancelSetup = useCallback(async () => {
    try {
      await invoke("cancel_harbor_setup");
      // Don't optimistically set status to "cancelled" here.
      // The backend will emit "harbour-setup-complete" with the actual
      // terminal status once the process is killed.  Setting it prematurely
      // causes a race where the complete event (which may carry "ready" if the
      // process finished between kill and status check) overwrites the
      // optimistic state.
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setRunning(false);
    }
  }, []);

  const dismissSuccess = useCallback(() => {
    setJustInstalled(false);
  }, []);

  useEffect(() => {
    if (!justInstalled) return;
    // Give users enough time to read the success screen and CLI version.
    // The "Get Started" button provides explicit dismissal; this is a fallback
    // for users who don't interact.
    const timer = setTimeout(() => setJustInstalled(false), 8000);
    return () => clearTimeout(timer);
  }, [justInstalled]);

  const value = useMemo<HarborSetupContextValue>(
    () => ({
      detail,
      loading,
      running,
      terminalOutput,
      error,
      ready: import.meta.env.VITE_FORCE_SETUP
        ? false
        : !loading && detail?.status === "ready" && !justInstalled,
      justInstalled,
      redetect,
      startSetup,
      writeSetupInput,
      cancelSetup,
      dismissSuccess,
    }),
    [detail, loading, running, terminalOutput, error, justInstalled, redetect, startSetup, writeSetupInput, cancelSetup, dismissSuccess],
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
