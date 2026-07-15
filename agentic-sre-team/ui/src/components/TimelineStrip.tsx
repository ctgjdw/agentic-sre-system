import type { Activity } from "../api/types";

// 24h environment-activity strip (wireframe note 10): signal-density bars with the
// suppressed portion shown dimmer, case-open markers colored by severity, and annotation
// ticks. Purely a scannable overview; no interaction yet.
export function TimelineStrip({ activity }: { activity: Activity }) {
  const max = Math.max(1, ...activity.buckets.map((b) => b.signals + b.suppressed));
  const w = 1200;
  const h = 42;
  const bw = w / Math.max(1, activity.buckets.length);
  const first = Date.parse(activity.buckets[0]?.ts ?? new Date().toISOString());
  const span = Math.max(1, Date.now() - first);
  const x = (iso: string) => ((Date.parse(iso) - first) / span) * w;
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      style={{ width: "100%", height: h, borderBottom: "1px solid var(--line-2)" }}
      aria-label="environment activity timeline"
      preserveAspectRatio="none"
    >
      {activity.buckets.map((b, i) => {
        const total = ((b.signals + b.suppressed) / max) * (h - 14);
        const solid = (b.signals / max) * (h - 14);
        return (
          <g key={b.ts}>
            <rect x={i * bw + 1} y={h - 8 - total} width={bw - 2} height={total} fill="var(--line)" />
            <rect x={i * bw + 1} y={h - 8 - solid} width={bw - 2} height={solid} fill="var(--ink-3)" />
          </g>
        );
      })}
      {activity.cases.map((c) => (
        <circle key={c.id} cx={x(c.created_at)} cy={6} r={3} fill={`var(--sev${c.severity})`} />
      ))}
      {activity.annotations.map((a, i) => (
        <rect key={i} x={x(a.ts)} y={0} width={1.5} height={h} fill="var(--accent)" />
      ))}
    </svg>
  );
}
