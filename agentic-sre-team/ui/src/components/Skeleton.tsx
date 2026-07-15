export const Skeleton = ({ width = "100%" }: { width?: string | number }) => (
  <div style={{ height: 10, width, background: "var(--line-2)", margin: "12px 0" }} />
);
