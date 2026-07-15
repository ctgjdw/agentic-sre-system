import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, apiPost } from "../api/client";
import type {
  CaseDetail,
  Evidence,
  Governance,
  RcaStructured,
  RunbookStructured,
} from "../api/types";
import { CitationChip } from "../components/CitationChip";

// Outcome preview text (wireframe notes 9, c): states exactly what approval does, in
// plain words, and reassures what it cannot do.
const PREVIEWS: Record<"rca" | "runbook", (draftMr: boolean) => string> = {
  rca: () =>
    "Approving publishes this RCA to the ops Telegram group and starts runbook drafting. " +
    "It does not change any system.",
  runbook: (draftMr) =>
    draftMr
      ? "Approving publishes the runbook to Telegram and opens a DRAFT PR/MR with the patch " +
        "on a new branch. The draft is never merged automatically."
      : "Approving publishes the runbook to Telegram and closes the case. It does not " +
        "change any system.",
};

const blockStyle = (accent = false): React.CSSProperties => ({
  border: `1px solid ${accent ? "var(--ink)" : "var(--line)"}`,
  padding: "12px 14px",
  marginBottom: 12,
});

const heading: React.CSSProperties = { fontSize: 13, color: "var(--ink)", display: "block", marginBottom: 6 };

function citedText(text: string, eids: string[], onEid: (e: string) => void) {
  return (
    <span>
      {text}
      {eids.map((e) => (
        <CitationChip key={e} eid={e} onClick={onEid} />
      ))}
    </span>
  );
}

export function ArtifactScreen() {
  const { id = "", kind = "rca" } = useParams<{ id: string; kind: "rca" | "runbook" }>();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [selectedEid, setSelectedEid] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [edited, setEdited] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showFailures, setShowFailures] = useState(false);

  const { data, isPending } = useQuery({
    queryKey: ["case", id],
    queryFn: () => api<CaseDetail>(`/api/cases/${id}`),
  });
  const { data: gov } = useQuery({
    queryKey: ["governance"],
    queryFn: () => api<Governance>("/api/governance"),
  });

  if (isPending) return <p className="dim mono" style={{ paddingTop: 16 }}>Loading artifact...</p>;
  if (!data) return <p className="dim">Case not found.</p>;

  const artifact = data.artifacts
    .filter((a) => a.kind === kind)
    .sort((a, b) => b.version - a.version)[0];
  if (!artifact) return <p className="dim">No {kind} drafted yet for this case.</p>;

  const c = data.case;
  const waitingHere = c.status === "waiting_approval" && c.phase === `gate_${kind}`;
  const verification = artifact.verification;
  const evById = new Map<string, Evidence>(data.evidence.map((e) => [e.eid, e]));
  const selected = selectedEid ? evById.get(selectedEid) : undefined;
  const body = artifact.body_edited_md ?? artifact.body_md;

  const onEid = (eid: string) => setSelectedEid(eid);

  const decide = async (decision: "approve" | "approve_with_edits" | "reject") => {
    const reviewer =
      localStorage.getItem("reviewer") ??
      window.prompt("Reviewer identity (logged with the approval):") ??
      "unknown";
    localStorage.setItem("reviewer", reviewer);
    const annotation =
      decision === "reject"
        ? (window.prompt("Why is this rejected? (goes back to the drafter)") ?? "")
        : "";
    setBusy(true);
    try {
      await apiPost(`/api/cases/${id}/decision`, {
        gate: kind,
        decision,
        decided_by: reviewer,
        channel: "ui",
        edited_body_md: decision === "approve_with_edits" ? (edited ?? body) : undefined,
        annotation,
      });
      qc.invalidateQueries({ queryKey: ["case", id] });
      navigate("/cases");
    } finally {
      setBusy(false);
    }
  };

  const reviewer = localStorage.getItem("reviewer");

  return (
    <section>
      <header style={{ display: "flex", gap: 10, alignItems: "center", padding: "10px 0" }}>
        <span className="mono dim">{c.display_id}</span>
        <b style={{ fontSize: 14 }}>
          {kind.toUpperCase()} v{artifact.version} · {c.title}
        </b>
        {verification && (
          <button
            className="mono"
            onClick={() => setShowFailures((s) => !s)}
            style={{
              border: "1px solid var(--line)",
              background: verification.verified ? "var(--line-2)" : "var(--accent-soft)",
              color: verification.verified ? "var(--ok)" : "var(--accent)",
              padding: "1px 8px",
            }}
          >
            citations verified {verification.checked - verification.failures.length}/{verification.checked}
          </button>
        )}
        {c.failure_class && <span className="mono dim">class: {c.failure_class}</span>}
        <span style={{ flex: 1 }} />
        <span className="mono dim">
          drafted by frontier tier · {artifact.model_id}
        </span>
      </header>

      {showFailures && verification && (
        <div className="mono" style={{ border: "1px solid var(--accent)", padding: "8px 12px", marginBottom: 12 }}>
          {verification.failures.length === 0 ? (
            <span className="dim">All {verification.checked} claims cite valid evidence. No failures.</span>
          ) : (
            verification.failures.map((f, i) => (
              <div key={i} style={{ color: "var(--accent)" }}>
                {f.claim} - {f.reason}
              </div>
            ))
          )}
        </div>
      )}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 30%",
          border: "1px solid var(--line)",
          minHeight: 430,
        }}
      >
        <div style={{ padding: 14 }}>
          {editing ? (
            <textarea
              value={edited ?? body}
              onChange={(e) => setEdited(e.target.value)}
              style={{
                width: "100%",
                minHeight: 380,
                background: "var(--paper)",
                color: "var(--ink)",
                border: "1px solid var(--line)",
                font: "12px/1.5 var(--mono)",
                padding: 10,
              }}
            />
          ) : kind === "rca" ? (
            <RcaBody structured={artifact.structured as unknown as RcaStructured} onEid={onEid} />
          ) : (
            <RunbookBody structured={artifact.structured as unknown as RunbookStructured} onEid={onEid} />
          )}
        </div>

        <div style={{ padding: 14, borderLeft: "1px solid var(--line-2)" }}>
          <h4 className="mono dim" style={{ margin: "0 0 10px", textTransform: "uppercase", letterSpacing: "0.08em" }}>
            Citation inspector
          </h4>
          {selected ? (
            <div>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <span className="mono" style={{ border: "1px solid var(--line)", padding: "0 6px", background: "var(--line-2)" }}>
                  {selected.eid}
                </span>
                <span className="mono dim">
                  {selected.toolset} · {selected.observed_at ? new Date(selected.observed_at).toLocaleTimeString() : ""}
                </span>
              </div>
              <p className="dim" style={{ fontSize: 13 }}>{selected.excerpt}</p>
              <div className="mono dim">query: {selected.invocation.slice(0, 160)}</div>
              {selected.source_url && (
                <a className="mono" href={selected.source_url} target="_blank" rel="noreferrer" style={{ color: "var(--accent)" }}>
                  open in Grafana -&gt;
                </a>
              )}
            </div>
          ) : (
            <p className="dim mono">Click a citation chip to inspect its evidence.</p>
          )}
          {verification && (
            <p className="mono dim" style={{ marginTop: 18 }}>
              Verifier: {verification.checked - verification.failures.length}/{verification.checked} claims cite
              evidence; {verification.failures.length} unsupported
              {kind === "rca"
                ? `; confidence ${(artifact.structured as unknown as RcaStructured).confidence.toFixed(2)}`
                : ""}
              .
            </p>
          )}
        </div>
      </div>

      <footer
        style={{
          display: "flex",
          gap: 10,
          alignItems: "center",
          padding: "12px 14px",
          borderTop: "1.5px dashed var(--accent)",
          background: "var(--accent-soft)",
        }}
      >
        {editing ? (
          <>
            <button className="mono" disabled={busy} onClick={() => decide("approve_with_edits")} style={btn(true)}>
              Save edits &amp; approve
            </button>
            <button className="mono" onClick={() => { setEditing(false); setEdited(null); }} style={btn(false)}>
              Cancel edits
            </button>
          </>
        ) : (
          <>
            <button className="mono" disabled={!waitingHere || busy} onClick={() => decide("approve")} style={btn(true)}>
              Approve
            </button>
            <button
              className="mono"
              disabled={!waitingHere || busy}
              onClick={() => { setEdited(body); setEditing(true); }}
              style={btn(false)}
            >
              Approve with edits
            </button>
            <button
              className="mono"
              disabled={!waitingHere || busy}
              onClick={() => decide("reject")}
              style={{ ...btn(false), borderColor: "var(--accent)", color: "var(--accent)" }}
            >
              Reject
            </button>
          </>
        )}
        <span className="dim" style={{ fontSize: 12 }}>
          {waitingHere
            ? PREVIEWS[kind](gov?.scm_draft_mr ?? false)
            : `This ${kind} is not currently awaiting a decision (case is ${c.status}).`}
        </span>
        <span style={{ flex: 1 }} />
        <span className="mono dim">reviewer: {reviewer ?? "unset"} · logged</span>
      </footer>
    </section>
  );
}

function RcaBody({ structured, onEid }: { structured: RcaStructured; onEid: (e: string) => void }) {
  return (
    <div>
      <div style={blockStyle(true)}>
        <b style={heading}>Immediate mitigation</b>
        <div className="dim">{structured.mitigation_md}</div>
      </div>
      <div style={blockStyle()}>
        <b style={heading}>Root cause</b>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          {structured.causal_chain.map((s, i) => (
            <span key={i} style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <span style={{ border: "1px solid var(--line)", background: "var(--panel-2)", padding: "4px 8px", fontSize: 12 }}>
                {citedText(s.step, s.eids, onEid)}
              </span>
              {i < structured.causal_chain.length - 1 && <span className="mono dim">-&gt;</span>}
            </span>
          ))}
        </div>
      </div>
      {(structured.blast_radius_md || structured.timeline.length > 0) && (
        <div style={blockStyle()}>
          <b style={heading}>Blast radius + timeline</b>
          {structured.blast_radius_md && <div className="dim">{structured.blast_radius_md}</div>}
          {structured.timeline.map((t, i) => (
            <div key={i} className="mono dim" style={{ marginTop: 4 }}>
              {citedText(`${t.ts} - ${t.text}`, t.eids, onEid)}
            </div>
          ))}
        </div>
      )}
      {structured.alternatives.length > 0 && (
        <div style={{ ...blockStyle(), borderStyle: "dashed" }}>
          <b style={heading}>Alternatives considered and rejected</b>
          {structured.alternatives.map((a, i) => (
            <div key={i} className="dim" style={{ marginTop: 4 }}>
              {citedText(`${a.statement}: ${a.why_rejected}`, a.eids, onEid)}
            </div>
          ))}
        </div>
      )}
      {structured.monitoring_gaps_md && (
        <div style={blockStyle()}>
          <b style={heading}>Monitoring gaps</b>
          <div className="dim">{structured.monitoring_gaps_md}</div>
        </div>
      )}
    </div>
  );
}

function RunbookBody({ structured, onEid }: { structured: RunbookStructured; onEid: (e: string) => void }) {
  void onEid;
  return (
    <div>
      {structured.patch_files && structured.patch_files.length > 0 && (
        <div style={blockStyle(true)}>
          <b style={heading}>Patch</b>
          {structured.patch_files.map((p, i) => (
            <div key={i} style={{ marginTop: 8 }}>
              <div className="mono dim">{p.path}</div>
              <pre
                className="mono"
                style={{ background: "var(--paper)", border: "1px solid var(--line)", padding: 10, overflowX: "auto", margin: "4px 0 0" }}
              >
                {p.content}
              </pre>
            </div>
          ))}
        </div>
      )}
      {structured.pre_checks.length > 0 && (
        <div style={blockStyle()}>
          <b style={heading}>Pre-checks</b>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {structured.pre_checks.map((s, i) => (
              <li key={i} className="dim">{s}</li>
            ))}
          </ul>
        </div>
      )}
      <div style={blockStyle()}>
        <b style={heading}>Steps</b>
        <ol style={{ margin: 0, paddingLeft: 18 }}>
          {structured.steps.map((s, i) => (
            <li key={i} className="dim" style={{ marginBottom: 6 }}>
              <b style={{ color: "var(--ink)" }}>{s.title}</b>
              {s.detail && <div>{s.detail}</div>}
              {s.command && (
                <pre
                  className="mono"
                  style={{ background: "var(--paper)", border: "1px solid var(--line)", padding: "6px 8px", margin: "4px 0 0", overflowX: "auto" }}
                >
                  {s.command}
                </pre>
              )}
            </li>
          ))}
        </ol>
      </div>
      {structured.post_checks.length > 0 && (
        <div style={blockStyle()}>
          <b style={heading}>Post-checks</b>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {structured.post_checks.map((s, i) => (
              <li key={i} className="dim">{s}</li>
            ))}
          </ul>
        </div>
      )}
      {structured.rollback.length > 0 && (
        <div style={blockStyle()}>
          <b style={heading}>Rollback</b>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {structured.rollback.map((s, i) => (
              <li key={i} className="dim">{s}</li>
            ))}
          </ul>
        </div>
      )}
      {structured.risk_notes_md && (
        <div style={{ ...blockStyle(), borderStyle: "dashed" }}>
          <b style={heading}>Risk notes</b>
          <div className="dim">{structured.risk_notes_md}</div>
        </div>
      )}
    </div>
  );
}

const btn = (primary: boolean): React.CSSProperties => ({
  border: `1px solid ${primary ? "var(--ink)" : "var(--line)"}`,
  background: primary ? "var(--ink)" : "var(--panel)",
  color: primary ? "var(--panel)" : "var(--ink)",
  padding: "6px 14px",
  fontSize: 12,
});
