// Shared types for the lint orchestrator and its passes.

export interface Finding {
  file: string; // repo-relative when possible; "(host)" / "(shellcheck)" for runner-level issues
  line?: number;
  column?: number;
  pass: "shellcheck" | "bash" | "compose";
  rule: string; // rule id (e.g. "HARBOR001") or shellcheck code (e.g. "SC2086")
  severity: "error" | "warning";
  message: string;
  fix?: string;
}
