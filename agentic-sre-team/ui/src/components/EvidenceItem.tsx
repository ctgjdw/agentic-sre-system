import type { Evidence } from "../api/types";

// An evidence receipt (wireframe note 10): source + timestamp, excerpt, the exact query,
// and a Grafana Explore deep link when the worker recorded a source_url (note 11). The
// E# IDs are the same ones the RCA cites. `selected` mirrors a chip click on the board.
export function EvidenceItem({ e, selected }: { e: Evidence; selected: boolean }) {
  return (
    <div
      id={`ev-${e.eid}`}
      style={{
        borderBottom: "1px solid var(--line-2)",
        padding: "8px 0",
        background: selected ? "var(--accent-soft)" : "transparent",
      }}
    >
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <span className="mono" style={{ border: "1px solid var(--line)", padding: "0 6px", background: "var(--line-2)" }}>
          {e.eid}
        </span>
        <span className="mono dim">
          {e.toolset} · {new Date(e.observed_at).toLocaleTimeString()}
        </span>
      </div>
      <div className="dim" style={{ fontSize: 13, margin: "4px 0", color: "var(--ink-2)" }}>
        {e.excerpt}
      </div>
      <div className="mono dim">
        query: {e.invocation.slice(0, 120)}{" "}
        {e.source_url && (
          <a href={e.source_url} target="_blank" rel="noreferrer" style={{ color: "var(--accent)" }}>
            open in Grafana -&gt;
          </a>
        )}
      </div>
    </div>
  );
}
