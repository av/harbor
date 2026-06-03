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
  redetect: () => Promise<void>;
  startSetup: () => Promise<void>;
  writeSetupInput: (data: string) => Promise<void>;
  cancelSetup: () => Promise<void>;
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

  const redetect = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await invoke<HarborSetupDetail>("detect_harbor_setup");
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
      const [unlistenOutput, unlistenStatus] = await Promise.all([
        listen<{ data: string }>("harbor-setup-terminal-output", (event) => {
          setTerminalOutput((prev) => {
            const next = prev + event.payload.data;
            return next.length > MAX_TERMINAL_OUTPUT
              ? next.slice(next.length - MAX_TERMINAL_OUTPUT)
              : next;
          });
        }),
        listen<{ status: string }>("harbor-setup-status", (event) => {
          setDetail((prev) => ({
            ...(prev ?? DEFAULT_DETAIL),
            status: event.payload.status,
            running: !TERMINAL_STATUSES.has(event.payload.status),
          }));
        }),
      ]);

      if (cancelled) {
        unlistenOutput();
        unlistenStatus();
        return;
      }

      unlisteners.push(unlistenOutput, unlistenStatus);
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
    let shouldRedetect = true;
    try {
      const next = await invoke<HarborSetupDetail>("start_harbor_setup");
      setDetail(next);
      shouldRedetect = false;
    } catch (e) {
      const rawMessage = e instanceof Error ? e.message : String(e);
      const message = rawMessage.replace(/^HARBOR_SETUP_STATUS=[^;]+;\s*/, "");
      const statusMatch = rawMessage.match(/HARBOR_SETUP_STATUS=([a-z-]+)/);
      setError(message);
      setDetail((prev) => ({
        ...(prev ?? DEFAULT_DETAIL),
        status: statusMatch?.[1] ?? "failed",
        lastError: message,
      }));
    } finally {
      setRunning(false);
      if (shouldRedetect) redetect();
    }
  }, [redetect]);

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
      setDetail((prev) => ({
        ...(prev ?? DEFAULT_DETAIL),
        status: "cancelled",
        running: false,
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }, []);

  const value = useMemo<HarborSetupContextValue>(
    () => ({
      detail,
      loading,
      running,
      terminalOutput,
      error,
      ready: !loading && detail?.status === "ready",
      redetect,
      startSetup,
      writeSetupInput,
      cancelSetup,
    }),
    [detail, loading, running, terminalOutput, error, redetect, startSetup, writeSetupInput, cancelSetup],
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
