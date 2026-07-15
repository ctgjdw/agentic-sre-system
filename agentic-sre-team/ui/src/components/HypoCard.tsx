import type { Hypothesis } from "../api/types";

// A single hypothesis. Confidence bar + for/against counts make disagreement visible
// (wireframe note 8); refuted cards dim to 0.55 but stay on screen with their evidence
// named (note 9) - showing pruned branches is what makes the surviving diagnosis credible.
export function HypoCard({ h, onEid }: { h: Hypothesis; onEid: (eid: string) => void }) {
  const chips = [...h.evidence_for, ...h.evidence_against];
  const refuted = h.status === "refuted";
  return (
    <div
      data-hypo
      style={{
        border: "1px solid var(--line)",
        padding: "10px 12px",
        marginBottom: 10,
        opacity: refuted ? 0.55 : 1,
      }}
    >
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <span
          className="mono"
          style={{
            border: "1px solid var(--line)",
            padding: "1px 8px",
            background: h.status === "supported" ? "var(--line-2)" : "transparent",
          }}
        >
          {h.hid} · {h.status.toUpperCase()}
        </span>
        <span className="mono dim num">confidence {h.confidence.toFixed(2)}</span>
      </div>
      <div className="dim" style={{ margin: "6px 0", color: "var(--ink-2)" }}>
        {h.statement}
      </div>
      <div style={{ height: 6, background: "var(--line-2)" }}>
        <div
          style={{
            height: 6,
            width: `${Math.round(h.confidence * 100)}%`,
            background: refuted ? "var(--ink-3)" : "var(--accent)",
          }}
        />
      </div>
      <div className="mono dim" style={{ marginTop: 6 }}>
        evidence: {h.evidence_for.length} for · {h.evidence_against.length} against{" "}
        {chips.map((eid) => (
          <button
            key={eid}
            onClick={() => onEid(eid)}
            className="mono"
            style={{
              border: "1px solid var(--line)",
              background: "none",
              color: "var(--ink-2)",
              marginLeft: 4,
              padding: "0 4px",
            }}
          >
            {eid}
          </button>
        ))}
      </div>
    </div>
  );
}
