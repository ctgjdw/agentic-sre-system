import { Fragment } from "react";
import type { StreamEvent } from "../api/types";

// Guarded graph nodes: these emit node_start / node_end (graph/deps.py guarded()).
const NAMES: Record<string, string> = {
  triage: "Triage",
  synthesize: "Synthesize",
  rca: "RCA",
  verify_citations: "Verify citations",
  remediate: "Remediate",
  publish: "Publish",
  park: "Park",
};

// Worker nodes are UNGUARDED (graph/build.py) so they emit NO node_start/node_end - the
// only trace they leave is tool_call / worker_warning events carrying a `worker` domain,
// plus a node_update on the worker node when they return. The ledger reconstructs a
// per-worker entry from those. Keys map the domain (event.worker) and the node name
// (event.node on node_update) to a display title.
const WORKER_NAMES: Record<string, string> = {
  metrics: "Metrics worker",
  logs: "Logs worker",
  infra: "Infra worker",
  changes: "Changes worker",
  ci: "CI worker",
};
const NODE_TO_DOMAIN: Record<string, string> = {
  metrics_worker: "metrics",
  logs_worker: "logs",
  infra_worker: "infra",
  changes_worker: "changes",
  ci_worker: "ci",
};

interface Entry {
  key: string;
  title: string;
  node: string | null;
  worker: string | null;
  live: boolean;
  intent: string; // latest streamed token: the live entry's stated intent, in place
  lines: StreamEvent[];
}

// Folds the raw StreamEvent[] into ledger entries: one per guarded node
// (node_start..node_end) and one per fanned-out worker per round (synthesized from its
// tool_call/worker_warning stream). Tokens collapse to the live entry's latest "intent"
// rather than accumulating as lines (wireframe note 6: reasoning transparency, not a
// spinner and not a log firehose).
function fold(events: StreamEvent[]): Entry[] {
  const entries: Entry[] = [];
  const byNode: Record<string, Entry> = {};
  // Worker entries for the current round, keyed by domain; reset on each `plan`.
  let roundWorkers: Record<string, Entry> = {};
  const liveTarget = () => entries.filter((x) => x.live).at(-1) ?? entries.at(-1);

  const finishWorkers = () => {
    for (const w of Object.values(roundWorkers)) w.live = false;
  };
  const workerEntry = (domain: string): Entry => {
    let entry = roundWorkers[domain];
    if (!entry) {
      entry = {
        key: `worker-${domain}-${entries.length}`,
        title: WORKER_NAMES[domain] ?? `${domain} worker`,
        node: null,
        worker: domain,
        live: true,
        intent: "",
        lines: [],
      };
      entries.push(entry);
      roundWorkers[domain] = entry;
    }
    return entry;
  };

  for (const e of events) {
    if (e.type === "node_start") {
      const node = String(e.node);
      // The `plan` node is guarded (emits node_start/end) AND make_plan emits a richer
      // custom `plan` event; skip the bare node entry so it isn't shown twice.
      if (node === "plan") continue;
      // A guarded node started: any still-open workers from the fan-out have joined.
      finishWorkers();
      const entry: Entry = {
        key: `${node}-${entries.length}`,
        title: NAMES[node] ?? node,
        node,
        worker: null,
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
        worker: null,
        live: false,
        intent: "",
        lines: [e],
      });
      roundWorkers = {}; // a new fan-out round starts fresh
    } else if (e.type === "node_update" && NODE_TO_DOMAIN[String(e.node)]) {
      // A worker node returned; close its entry (workers have no node_end).
      const w = roundWorkers[NODE_TO_DOMAIN[String(e.node)]];
      if (w) w.live = false;
    } else if (e.type === "token") {
      const target = liveTarget();
      if (target) target.intent = String(e.text ?? "");
    } else if (e.type === "tool_call") {
      // Workers emit start_tool_calling then tool_calling_result; render one line per
      // completed call (the result phase) so a call isn't shown twice. Route to the
      // emitting worker's entry (creating it on first sight).
      if (e.phase === "tool_result") {
        const target = e.worker ? workerEntry(String(e.worker)) : liveTarget();
        target?.lines.push(e);
      }
    } else if (e.type === "worker_warning") {
      const target = e.worker ? workerEntry(String(e.worker)) : liveTarget();
      target?.lines.push(e);
    } else if (["gate_waiting", "parked", "error", "context_added"].includes(e.type)) {
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
