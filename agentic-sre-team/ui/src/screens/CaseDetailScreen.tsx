import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api, apiPost } from "../api/client";
import { useCaseStream } from "../api/sse";
import type { CaseDetail } from "../api/types";
import { Ledger } from "../components/Ledger";
import { PhaseChip } from "../components/PhaseChip";
import { SevPill } from "../components/SevPill";
import { Skeleton } from "../components/Skeleton";

const paneStyle = (bordered: boolean): React.CSSProperties => ({
  padding: 12,
  ...(bordered ? { borderLeft: "1px solid var(--line-2)" } : {}),
});

const paneHeadStyle: React.CSSProperties = {
  margin: "0 0 10px",
  fontSize: 11,
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  color: "var(--ink-3)",
  fontWeight: 600,
};

export function CaseDetailScreen() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const { events, connected } = useCaseStream(id);
  const { data, isPending } = useQuery({
    queryKey: ["case", id],
    queryFn: () => api<CaseDetail>(`/api/cases/${id}`),
  });

  if (isPending) {
    return (
      <section style={{ paddingTop: 12 }}>
        <Skeleton width="45%" />
        <Skeleton width="80%" />
        <Skeleton width="70%" />
      </section>
    );
  }
  if (!data) return <p className="dim">Case not found.</p>;

  const c = data.case;
  const waitingGate = c.phase === "gate_rca" ? "rca" : c.phase === "gate_runbook" ? "runbook" : null;
  const grafana = data.evidence.find((e) => e.source_url)?.source_url ?? null;

  const park = async (reason: string) => {
    await apiPost(`/api/cases/${id}/park`, { reason, actor: "console" });
    qc.invalidateQueries({ queryKey: ["case", id] });
  };
  const resume = async () => {
    await apiPost(`/api/cases/${id}/resume`, { actor: "console" });
    qc.invalidateQueries({ queryKey: ["case", id] });
  };
  const addContext = async () => {
    const text = window.prompt("Context for the agents (lands at the next node):");
    if (text) await apiPost(`/api/cases/${id}/context`, { text, author: "console" });
  };

  return (
    <section>
      {!connected && (
        <div className="mono" style={{ background: "var(--accent-soft)", padding: "4px 10px", marginTop: 8 }}>
          Live stream reconnecting - showing last saved state.
        </div>
      )}
      <header style={{ display: "flex", gap: 10, alignItems: "center", padding: "10px 0" }}>
        <span className="mono dim">{c.display_id}</span>
        <b style={{ fontSize: 14 }}>{c.title}</b>
        <SevPill severity={c.severity} />
        <PhaseChip phase={c.phase} />
        {c.status === "open" && (
          <span className="mono dim num">round {c.round} of 2</span>
        )}
        <span style={{ flex: 1 }} />
        {grafana && (
          <a className="mono dim" href={grafana} target="_blank" rel="noreferrer">
            Open in Grafana
          </a>
        )}
        <button className="mono" onClick={() => park("manual escalation")} style={btn}>
          Escalate to human
        </button>
        <button
          className="mono"
          onClick={() => park("paused by operator")}
          style={{ ...btn, color: "var(--accent)", borderColor: "var(--accent)" }}
        >
          Pause case
        </button>
      </header>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "33% 1fr 30%",
          gap: 0,
          border: "1px solid var(--line)",
          minHeight: 430,
        }}
      >
        <div style={paneStyle(false)}>
          <h4 className="mono" style={paneHeadStyle}>
            Progress ledger
          </h4>
          <Ledger events={events} />
        </div>
        <div style={paneStyle(true)} data-pane="board">
          <h4 className="mono" style={paneHeadStyle}>
            Hypothesis board
          </h4>
          <p className="dim mono">Hypothesis board (Task 30).</p>
        </div>
        <div style={paneStyle(true)} data-pane="evidence">
          <h4 className="mono" style={paneHeadStyle}>
            Evidence
          </h4>
          <p className="dim mono">Evidence pane (Task 30).</p>
        </div>
      </div>

      <footer
        style={{
          display: "flex",
          gap: 10,
          alignItems: "center",
          padding: "10px 12px",
          borderTop: "1.5px dashed var(--accent)",
          background: "var(--accent-soft)",
        }}
      >
        {waitingGate ? (
          <Link
            to={`/cases/${id}/artifact/${waitingGate}`}
            className="mono"
            style={{ color: "var(--accent)" }}
          >
            Decision needed: review the {waitingGate} now
          </Link>
        ) : c.status === "needs_human" ? (
          <>
            <span className="mono" style={{ color: "var(--accent)" }}>
              Parked: {c.halt_reason}
            </span>
            <button className="mono" onClick={resume} style={btn}>
              Resume
            </button>
          </>
        ) : c.status === "closed" ? (
          <span className="mono dim">Case closed. Artifacts published.</span>
        ) : (
          <span className="mono dim">
            No decision needed yet. You will be pinged on Telegram when a gate is reached.
          </span>
        )}
        <span style={{ flex: 1 }} />
        <button className="mono" onClick={addContext} style={btn}>
          Add context for the agents
        </button>
      </footer>
    </section>
  );
}

const btn: React.CSSProperties = {
  border: "1px solid var(--line)",
  color: "var(--ink)",
  background: "var(--panel)",
  padding: "4px 12px",
};
