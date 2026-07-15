// Types mirror the gateway JSON verbatim (gateway/src/sre_gateway/api/*.py).
// Keep these in lockstep with the serializers there.

export type CaseKind = "incident" | "pipeline_failure";
export type CaseStatus = "open" | "waiting_approval" | "needs_human" | "closed";
export type Severity = 1 | 2 | 3 | 4;

export interface CaseSummary {
  id: string;
  display_id: string;
  kind: CaseKind;
  status: CaseStatus;
  phase: string;
  title: string;
  severity: Severity;
  effort: string;
  round: number;
  failure_class: string | null;
  spend_usd: number;
  tokens_in: number;
  tokens_out: number;
  tool_calls: number;
  halt_reason: string | null;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
}

export interface SignalItem {
  id: string;
  source: string;
  reporter: string;
  summary: string;
  fingerprint: string;
  labels: Record<string, string>;
  is_primary: boolean;
  attach_reason: string;
  received_at: string;
}

export interface Hypothesis {
  hid: string;
  statement: string;
  status: "open" | "supported" | "refuted";
  confidence: number;
  evidence_for: string[];
  evidence_against: string[];
  round: number;
  updated_at: string;
}

export interface Evidence {
  eid: string;
  worker: string;
  toolset: string;
  invocation: string;
  excerpt: string;
  source_url: string | null;
  observed_at: string;
  hypothesis_links: { hid: string; direction: "for" | "against" }[];
}

export interface Verification {
  verified: boolean;
  checked: number;
  failures: { claim: string; reason: string }[];
}

export interface Artifact {
  kind: "rca" | "runbook";
  version: number;
  structured: Record<string, unknown>;
  body_md: string;
  body_edited_md: string | null;
  verification: Verification | null;
  model_id: string;
  created_at: string;
}

// Shapes of Artifact.structured (RcaOut / RunbookOut .model_dump() from the graph nodes).
export interface CausalStep {
  step: string;
  eids: string[];
}
export interface TimelineEntry {
  ts: string;
  text: string;
  eids: string[];
}
export interface Alternative {
  statement: string;
  why_rejected: string;
  eids: string[];
}
export interface Claim {
  text: string;
  eids: string[];
}
export interface RcaStructured {
  mitigation_md: string;
  causal_chain: CausalStep[];
  blast_radius_md: string;
  timeline: TimelineEntry[];
  alternatives: Alternative[];
  monitoring_gaps_md: string;
  claims: Claim[];
  confidence: number;
}
export interface RunbookStep {
  title: string;
  detail: string;
  command: string | null;
}
export interface PatchFile {
  path: string;
  content: string;
}
export interface RunbookStructured {
  pre_checks: string[];
  steps: RunbookStep[];
  post_checks: string[];
  rollback: string[];
  risk_notes_md: string;
  patch_files: PatchFile[] | null;
}

export interface Approval {
  gate: string;
  decision: string;
  decided_by: string;
  channel: string;
  annotation: string;
  diff: string | null;
  decided_at: string;
}

export interface CaseDetail {
  case: CaseSummary;
  signals: SignalItem[];
  hypotheses: Hypothesis[];
  evidence: Evidence[];
  artifacts: Artifact[];
  approvals: Approval[];
}

export interface AgentGovernance {
  agent: string;
  tier: string;
  tools: string[];
  usd_per_day: number;
  spend_today: number;
}

export interface Governance {
  paused: boolean;
  agents: AgentGovernance[];
  suppression_24h: Record<string, number>;
  cases_opened_24h: number;
  running_cases: number;
  // Added in Phase 7 (Task 41); optional until then.
  scm_draft_mr?: boolean;
}

export interface Activity {
  buckets: { ts: string; signals: number; suppressed: number }[];
  cases: { id: string; display_id: string; severity: number; kind: string; created_at: string }[];
  annotations: { ts: string; text: string; kind: string }[];
}

export interface AuditEventRow {
  id: string;
  ts: string;
  case_id: string | null;
  actor: string;
  event_type: string;
  payload: Record<string, unknown>;
}

export interface Health {
  status: string;
  service: string;
  components: Record<string, string>;
}

// SSE frames. The gateway sets `event:` to the type and serializes the payload
// as JSON in `data:`; useCaseStream folds the type back in as `type`.
export interface StreamEvent {
  type: string;
  seq?: number;
  [k: string]: unknown;
}
