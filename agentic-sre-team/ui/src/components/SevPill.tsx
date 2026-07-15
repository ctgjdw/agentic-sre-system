export const SevPill = ({ severity }: { severity: number }) => (
  <span
    className="mono"
    style={{ border: `1px solid var(--sev${severity})`, color: `var(--sev${severity})`, padding: "1px 8px" }}
  >
    SEV-{severity}
  </span>
);
