// A superscript [E#] receipt inside artifact prose. Clicking loads that evidence into
// the citation inspector (wireframe note 6): every claim is a receipt, trust is verified.
export const CitationChip = ({ eid, onClick }: { eid: string; onClick: (eid: string) => void }) => (
  <button
    onClick={() => onClick(eid)}
    className="mono"
    style={{
      border: "1px solid var(--line)",
      background: "none",
      color: "var(--ink-3)",
      fontSize: 10,
      padding: "0 4px",
      marginLeft: 3,
      verticalAlign: "super",
    }}
  >
    {eid}
  </button>
);
