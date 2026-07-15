import { useQuery } from "@tanstack/react-query";
import { Link, useLocation } from "react-router-dom";
import { api, apiPost } from "../api/client";
import type { Governance, Health } from "../api/types";

const linkStyle = (active: boolean): React.CSSProperties => ({
  color: active ? "var(--ink)" : "var(--ink-3)",
  textDecoration: "none",
});

export function TopBar() {
  const { pathname } = useLocation();
  const { data: gov, refetch } = useQuery({
    queryKey: ["governance"],
    queryFn: () => api<Governance>("/api/governance"),
  });
  const { data: health } = useQuery({
    queryKey: ["healthz"],
    queryFn: () => api<Health>("/api/healthz"),
  });

  const running = gov?.running_cases ?? 0;
  const idle = gov ? Math.max(0, gov.agents.length - running) : 0;
  const degraded = health ? health.status !== "ok" : false;

  const pause = async () => {
    const next = !gov?.paused;
    const msg = next
      ? "Pause ALL agents? Intake and running cases halt at the next node. Audit-logged."
      : "Resume all agents?";
    if (window.confirm(msg)) {
      await apiPost("/api/governance/pause", { paused: next, actor: "console" });
      refetch();
    }
  };

  return (
    <header
      style={{
        display: "flex",
        gap: 14,
        alignItems: "center",
        padding: "10px 16px",
        borderBottom: "1px solid var(--line)",
        background: "var(--panel)",
      }}
    >
      <Link
        to="/cases"
        style={{ color: "var(--ink)", fontWeight: 700, letterSpacing: "0.02em", textDecoration: "none" }}
      >
        SRE TEAM
      </Link>
      <span
        className="mono"
        title={
          health
            ? Object.entries(health.components)
                .map(([k, v]) => `${k}: ${v}`)
                .join(" · ") || "no components reported"
            : "checking health"
        }
        style={{ color: degraded ? "var(--accent)" : "var(--ink-3)" }}
      >
        env: local-docker
      </span>
      <Link to="/cases" className="mono" style={linkStyle(pathname.startsWith("/cases"))}>
        cases
      </Link>
      <Link to="/chat" className="mono" style={linkStyle(pathname.startsWith("/chat"))}>
        chat
      </Link>
      <span style={{ flex: 1 }} />
      <Link
        to="/governance"
        className="mono num"
        style={linkStyle(pathname.startsWith("/governance"))}
      >
        agents: {idle} idle · {running} running
      </Link>
      <button
        onClick={pause}
        className="mono"
        style={{
          color: "var(--accent)",
          border: "1px solid var(--accent)",
          background: gov?.paused ? "var(--accent-soft)" : "transparent",
          padding: "4px 10px",
        }}
      >
        {gov?.paused ? "PAUSED - RESUME" : "PAUSE ALL"}
      </button>
    </header>
  );
}
