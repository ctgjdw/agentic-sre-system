// Today's spend against the manifest cap (wireframe note 1). Fills toward the accent
// as it nears the cap; a breach halts + pages (documented on the governance screen).
export function BudgetBar({ spend, cap }: { spend: number; cap: number }) {
  const ratio = cap > 0 ? Math.min(1, spend / cap) : 0;
  const hot = ratio > 0.8;
  return (
    <div style={{ height: 8, background: "var(--line-2)", margin: "8px 0 4px" }}>
      <div
        style={{
          height: 8,
          width: `${Math.round(ratio * 100)}%`,
          background: hot ? "var(--accent)" : "var(--ink-3)",
        }}
      />
    </div>
  );
}
