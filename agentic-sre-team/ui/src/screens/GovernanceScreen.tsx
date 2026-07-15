import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, apiPost } from "../api/client";
import type { AuditEventRow, Governance } from "../api/types";
import { BudgetBar } from "../components/BudgetBar";

// Suppression counters (wireframe note 4): what the system did NOT wake an agent for.
// Keys mirror api/governance.py SUPPRESSION_REASONS.
const COUNTERS: [string, string][] = [
  ["dedup", "deduped"],
  ["debounce", "debounced"],
  ["burst", "burst-suppressed"],
  ["grouped", "grouped"],
  ["paused", "paused-drops"],
];

const time = (iso: string) => new Date(iso).toLocaleTimeString();

// Renders one audit event as a readable, newest-first line (wireframe note 5).
function summarize(e: AuditEventRow): string {
  const p = e.payload ?? {};
  switch (e.event_type) {
    case "approval":
      return `${p.gate} ${p.decision} by ${e.actor}${p.edited ? " (edited)" : ""}`;
    case "llm_call":
      return `${p.node ?? p.agent ?? ""} · ${p.model_id ?? ""} · in ${p.tokens_in ?? "?"} out ${p.tokens_out ?? "?"} tok`;
    case "tool_call":
      return `${p.toolset ?? ""} · ${p.actor ?? e.actor}${p.degraded ? " (degraded)" : ""}`;
    case "suppression":
      return `${p.reason ?? "suppressed"} ${p.detail ?? ""}`.trim();
    case "intake":
      return `${p.reason ?? "intake"}`;
    case "budget":
      return `budget ${p.action ?? ""}${p.manual ? " (manual)" : ""}`.trim();
    default:
      return e.event_type;
  }
}

export function GovernanceScreen() {
  const qc = useQueryClient();
  const [expanded, setExpanded] = useState<string | null>(null);
  const { data: gov } = useQuery({
    queryKey: ["governance"],
    queryFn: () => api<Governance>("/api/governance"),
  });
  const { data: audit } = useQuery({
    queryKey: ["governance-audit"],
    queryFn: () => api<{ events: AuditEventRow[] }>("/api/governance/audit?limit=100"),
  });

  const pauseAll = async () => {
    const next = !gov?.paused;
    if (
      window.confirm(
        next ? "Pause ALL agents? Intake and running cases halt at the next node. Audit-logged." : "Resume all agents?",
      )
    ) {
      await apiPost("/api/governance/pause", { paused: next, actor: "console" });
      qc.invalidateQueries({ queryKey: ["governance"] });
    }
  };

  return (
    <section style={{ paddingTop: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
        <b style={{ letterSpacing: "0.04em" }}>GOVERNANCE</b>
        <span style={{ flex: 1 }} />
        <button
          onClick={pauseAll}
          className="mono"
          style={{
            color: "var(--accent)",
            border: "1px solid var(--accent)",
            background: gov?.paused ? "var(--accent-soft)" : "transparent",
            padding: "4px 10px",
          }}
        >
          {gov?.paused ? "PAUSED - RESUME ALL" : "PAUSE ALL AGENTS"}
        </button>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: 10,
          marginBottom: 16,
        }}
      >
        {(gov?.agents ?? []).map((a) => {
          const frontier = a.tier === "frontier";
          const open = expanded === a.agent;
          return (
            <div
              key={a.agent}
              style={{ border: `1px solid ${frontier ? "var(--ink)" : "var(--line)"}`, padding: "10px 12px" }}
            >
              <div style={{ display: "flex", gap: 6, alignItems: "baseline" }}>
                <b style={{ fontSize: 12, color: "var(--ink)" }}>{a.agent}</b>
                <span className="mono dim">{a.tier}</span>
              </div>
              <BudgetBar spend={a.spend_today} cap={a.usd_per_day} />
              <span className="mono dim num">
                ${a.spend_today.toFixed(2)} / ${a.usd_per_day.toFixed(2)} today
              </span>
              <button
                onClick={() => setExpanded(open ? null : a.agent)}
                className="mono dim"
                style={{ display: "block", marginTop: 8, border: "1px dashed var(--line)", background: "none", color: "var(--ink-3)", padding: "3px 6px", width: "100%", textAlign: "left" }}
              >
                tools: {a.tools.length} · manifest
              </button>
              {open && (
                <ul className="mono dim" style={{ margin: "6px 0 0", paddingLeft: 16 }}>
                  {a.tools.length === 0 ? <li>no tools declared</li> : a.tools.map((t) => <li key={t}>{t}</li>)}
                </ul>
              )}
            </div>
          );
        })}
      </div>

      <div
        style={{
          display: "flex",
          gap: 8,
          alignItems: "center",
          flexWrap: "wrap",
          padding: "10px 0",
          borderTop: "1px solid var(--line-2)",
          borderBottom: "1px solid var(--line-2)",
        }}
      >
        {COUNTERS.map(([key, label]) => (
          <span key={key} className="mono num" style={{ border: "1px solid var(--line)", padding: "3px 10px", color: "var(--ink-2)" }}>
            {label}: {gov?.suppression_24h?.[key] ?? 0}
          </span>
        ))}
        <span className="mono num" style={{ border: "1px solid var(--line)", padding: "3px 10px", color: "var(--ink-2)" }}>
          cases opened: {gov?.cases_opened_24h ?? 0}
        </span>
        <span style={{ flex: 1 }} />
        <span className="mono dim">every suppression logged</span>
      </div>

      <div style={{ padding: "14px 0" }}>
        <h4 className="mono dim" style={{ margin: "0 0 10px", textTransform: "uppercase", letterSpacing: "0.08em" }}>
          Audit stream
        </h4>
        <div className="mono dim" style={{ display: "grid", gap: 6 }}>
          {(audit?.events ?? []).map((e) => (
            <span key={e.id}>
              {time(e.ts)} · {e.case_id ?? "system"} · {e.event_type} · {summarize(e)}
            </span>
          ))}
          {audit && audit.events.length === 0 && <span>No audit events yet.</span>}
        </div>
      </div>
    </section>
  );
}
