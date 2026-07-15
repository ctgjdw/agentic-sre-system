import { Fragment } from "react";
import type { StreamEvent } from "../api/types";

const NAMES: Record<string, string> = {
  triage: "Triage",
  plan: "Plan",
  metrics_worker: "Metrics worker",
  logs_worker: "Logs worker",
  infra_worker: "Infra worker",
  changes_worker: "Changes worker",
  ci_worker: "CI worker",
  synthesize: "Synthesize",
  rca: "RCA",
  verify_citations: "Verify citations",
  remediate: "Remediate",
  publish: "Publish",
  park: "Park",
};

interface Entry {
  key: string;
  title: string;
  node: string | null;
  live: boolean;
  intent: string; // latest streamed token: the live entry's stated intent, in place
  lines: StreamEvent[];
}

// Folds the raw StreamEvent[] into one entry per graph node (node_start..node_end),
// with plan/tool_call/warning/terminal lines attached to the currently-live node.
// Tokens are collapsed to the entry's latest "intent" rather than accumulated as lines
// (wireframe note 6: reasoning transparency, not a spinner and not a log firehose).
function fold(events: StreamEvent[]): Entry[] {
  const entries: Entry[] = [];
  const byNode: Record<string, Entry> = {};
  const liveTarget = () => entries.filter((x) => x.live).at(-1) ?? entries.at(-1);

  for (const e of events) {
    if (e.type === "node_start") {
      const node = String(e.node);
      const entry: Entry = {
        key: `${node}-${entries.length}`,
        title: NAMES[node] ?? node,
        node,
        live: true,
        intent: "",
        lines: [],
      };
      entries.push(entry);
      byNode[node] = entry;
    } else if (e.type === "node_end") {
      const entry = byNode[String(e.node)];
      if (entry) entry.live = false;
    } else if (e.type === "plan") {
      entries.push({
        key: `plan-${entries.length}`,
        title: "Plan · deterministic",
        node: null,
        live: false,
        intent: "",
        lines: [e],
      });
    } else if (e.type === "token") {
      const target = liveTarget();
      if (target) target.intent = String(e.text ?? "");
    } else if (e.type === "tool_call") {
      // Workers emit start_tool_calling then tool_calling_result; render one line per
      // completed call (the result phase) so a call isn't shown twice.
      if (e.phase === "tool_result") liveTarget()?.lines.push(e);
    } else if (["worker_warning", "gate_waiting", "parked", "error", "context_added"].includes(e.type)) {
      liveTarget()?.lines.push(e);
    }
  }
  return entries;
}

export function Ledger({ events }: { events: StreamEvent[] }) {
  const entries = fold(events);
  if (entries.length === 0) {
    return <p className="dim mono">Waiting for the first agent to start...</p>;
  }
  return (
    <div>
      {entries.map((entry) => (
        <div
          key={entry.key}
          data-live={entry.live || undefined}
          style={{
            borderLeft: `2px solid ${entry.live ? "var(--accent)" : "var(--line)"}`,
            padding: "2px 0 10px 12px",
            marginLeft: 4,
          }}
        >
          <b style={{ fontSize: 12, display: "block", color: "var(--ink)" }}>
            {entry.title}
            {entry.live ? " · running" : ""}
          </b>
          {entry.live && entry.intent && (
            <span className="dim" style={{ fontSize: 12 }}>
              {entry.intent}
            </span>
          )}
          {entry.lines.map((line, i) => (
            <Fragment key={i}>
              {line.type === "plan" && (
                <div className="mono dim">
                  fan-out: {(line.workers as string[]).join(", ")} (effort {String(line.effort)}, round{" "}
                  {String(line.round)})
                </div>
              )}
              {line.type === "tool_call" && (
                <div
                  className="mono dim"
                  style={{
                    border: "1px dashed var(--line)",
                    padding: "3px 8px",
                    marginTop: 4,
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                  }}
                >
                  <span>
                    holmes:{String(line.toolset || line.tool_name)} · {String(line.description)}
                  </span>
                </div>
              )}
              {line.type === "worker_warning" && (
                <div className="mono" style={{ color: "var(--sev2)", marginTop: 4 }}>
                  degraded: {String(line.worker)} - {String(line.error)}
                </div>
              )}
              {line.type === "gate_waiting" && (
                <div className="mono" style={{ color: "var(--accent)", marginTop: 4 }}>
                  waiting on gate: {String(line.gate ?? "")}
                </div>
              )}
              {line.type === "context_added" && (
                <div className="mono dim" style={{ marginTop: 4 }}>
                  context added by {String(line.author ?? "human")}: {String(line.text ?? "")}
                </div>
              )}
              {(line.type === "parked" || line.type === "error") && (
                <div className="mono" style={{ color: "var(--accent)", marginTop: 4 }}>
                  {line.type}: {String(line.reason ?? line.error ?? "")}
                </div>
              )}
            </Fragment>
          ))}
        </div>
      ))}
    </div>
  );
}
