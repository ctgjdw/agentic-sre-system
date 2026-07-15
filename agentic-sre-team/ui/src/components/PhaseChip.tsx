// Maps a graph phase (cases.phase, set by graph/deps.py node_end) to the operator-facing
// label from wireframe screen 1. Unknown phases fall through to the raw value.
const LABELS: Record<string, string> = {
  triage: "Triaging",
  plan: "Planning",
  metrics_worker: "Investigating",
  logs_worker: "Investigating",
  infra_worker: "Investigating",
  changes_worker: "Investigating",
  ci_worker: "Investigating",
  synthesize: "Synthesizing",
  rca: "Drafting RCA",
  verify_citations: "Verifying",
  gate_rca: "RCA awaiting review",
  remediate: "Drafting runbook",
  gate_runbook: "Runbook awaiting review",
  publish: "Publishing",
  closed: "Closed",
  parked: "Needs human",
  queued: "Queued",
};

export const PhaseChip = ({ phase }: { phase: string }) => (
  <span
    className="mono"
    style={{ border: "1px solid var(--line)", padding: "1px 8px", color: "var(--ink-2)" }}
  >
    {LABELS[phase] ?? phase}
  </span>
);
