// The only animated element in the product: a gentle pulse marking a case whose agent
// is actively streaming. Motion is reserved for real streaming state (visual direction).
export const LiveDot = () => (
  <span className="mono live-dot" style={{ color: "var(--accent)" }}>
    ● live
  </span>
);
