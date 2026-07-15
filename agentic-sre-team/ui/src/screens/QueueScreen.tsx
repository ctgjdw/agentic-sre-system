import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Activity, CaseSummary, Health } from "../api/types";
import { LiveDot } from "../components/LiveDot";
import { PhaseChip } from "../components/PhaseChip";
import { SevPill } from "../components/SevPill";
import { Skeleton } from "../components/Skeleton";
import { TimelineStrip } from "../components/TimelineStrip";

// "Needs you" is the default tab (wireframe note 3): the queue is a to-do list of
// decisions, not a monitoring wall.
const TABS = [
  ["needs_you", "Needs you", (c: CaseSummary) => c.status === "waiting_approval"],
  ["active", "Active", (c: CaseSummary) => c.status === "open"],
  ["needs_human", "Needs human", (c: CaseSummary) => c.status === "needs_human"],
  ["closed", "Closed", (c: CaseSummary) => c.status === "closed"],
] as const;

type TabKey = (typeof TABS)[number][0];

const mins = (iso: string) => `${Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000))}m`;

// A waiting case's primary action jumps straight to the artifact it needs a decision on;
// everything else is watch-only (wireframe note 4).
function action(c: CaseSummary): { label: string; to: string } {
  if (c.phase === "gate_rca") return { label: "Review RCA", to: `/cases/${c.id}/artifact/rca` };
  if (c.phase === "gate_runbook")
    return { label: "Review runbook", to: `/cases/${c.id}/artifact/runbook` };
  return { label: "Watch", to: `/cases/${c.id}` };
}

export function QueueScreen() {
  const [tab, setTab] = useState<TabKey>("needs_you");
  const cases = useQuery({
    queryKey: ["cases"],
    queryFn: () => api<{ cases: CaseSummary[] }>("/api/cases"),
  });
  const activity = useQuery({
    queryKey: ["activity"],
    queryFn: () => api<Activity>("/api/activity?hours=24"),
  });
  const health = useQuery({
    queryKey: ["healthz"],
    queryFn: () => api<Health>("/api/healthz"),
  });

  if (cases.isPending) {
    return (
      <div>
        {[80, 65, 72].map((w) => (
          <Skeleton key={w} width={`${w}%`} />
        ))}
      </div>
    );
  }

  const all = cases.data?.cases ?? [];
  const rows = all
    .filter(TABS.find(([k]) => k === tab)![2])
    // waiting-on-a-human sorts above everything (wireframe note 3), then most recent first.
    .sort((a, b) => {
      const aw = a.status === "waiting_approval" ? 0 : 1;
      const bw = b.status === "waiting_approval" ? 0 : 1;
      if (aw !== bw) return aw - bw;
      return Date.parse(b.created_at) - Date.parse(a.created_at);
    });

  const lastClosed = all.find((c) => c.closed_at)?.closed_at ?? null;
  const components = health.data?.components ?? {};

  return (
    <section>
      <nav style={{ display: "flex", gap: 8, padding: "10px 0" }}>
        {TABS.map(([key, label, pred]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className="mono num"
            style={{
              border: "1px solid var(--line)",
              padding: "3px 10px",
              background: tab === key ? "var(--line-2)" : "transparent",
              color: tab === key ? "var(--ink)" : "var(--ink-2)",
            }}
          >
            {label} ({all.filter(pred).length})
          </button>
        ))}
      </nav>

      {activity.data && <TimelineStrip activity={activity.data} />}

      {rows.length === 0 && (
        <p className="dim" style={{ padding: "20px 8px" }}>
          No cases here.{" "}
          {lastClosed ? `Last case closed ${mins(lastClosed)} ago. ` : ""}
          Intake is healthy:{" "}
          {Object.entries(components)
            .map(([k, v]) => `${k} ${v}`)
            .join(", ") || "starting"}
          .
        </p>
      )}

      {rows.map((c) => {
        const act = action(c);
        const waiting = c.status === "waiting_approval";
        return (
          <div
            key={c.id}
            style={{
              display: "flex",
              gap: 12,
              alignItems: "center",
              padding: "10px 8px",
              borderBottom: "1px solid var(--line-2)",
              background: waiting ? "var(--accent-soft)" : "transparent",
            }}
          >
            {c.kind === "pipeline_failure" ? (
              <span
                className="mono"
                style={{ border: "1px solid var(--line)", padding: "1px 6px", color: "var(--ink-2)" }}
              >
                PIPELINE
              </span>
            ) : (
              <span style={{ width: 4, alignSelf: "stretch", background: `var(--sev${c.severity})` }} />
            )}
            <span className="mono dim">{c.display_id}</span>
            <Link to={`/cases/${c.id}`} style={{ color: "var(--ink)", textDecoration: "none" }}>
              {c.title}
            </Link>
            <SevPill severity={c.severity} />
            {c.failure_class && <span className="mono dim">class: {c.failure_class}</span>}
            <PhaseChip phase={c.phase} />
            {c.status === "open" && <LiveDot />}
            <span style={{ flex: 1 }} />
            <span className="mono dim num">
              {waiting ? `waiting ${mins(c.updated_at)}` : `${mins(c.created_at)} elapsed`}
            </span>
            <span className="mono dim num">${c.spend_usd.toFixed(2)}</span>
            <Link
              to={act.to}
              className="mono"
              style={{
                border: "1px solid var(--line)",
                padding: "3px 10px",
                color: "var(--ink)",
                textDecoration: "none",
                whiteSpace: "nowrap",
              }}
            >
              {act.label}
            </Link>
          </div>
        );
      })}
    </section>
  );
}
