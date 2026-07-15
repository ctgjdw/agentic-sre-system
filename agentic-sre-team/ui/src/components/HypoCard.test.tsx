import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { HypoCard } from "./HypoCard";

const H = {
  hid: "H3",
  statement: "Host CPU saturation",
  status: "refuted" as const,
  confidence: 0.05,
  evidence_for: [],
  evidence_against: ["E2"],
  round: 1,
  updated_at: new Date().toISOString(),
};

test("refuted hypothesis is dimmed and lists refuting evidence", () => {
  const onEid = vi.fn();
  render(<HypoCard h={H} onEid={onEid} />);
  expect(screen.getByText(/H3 · REFUTED/)).toBeInTheDocument();
  const card = screen.getByText(/Host CPU saturation/).closest("div[data-hypo]")!;
  expect(card).toHaveStyle({ opacity: "0.55" });
  screen.getByRole("button", { name: "E2" }).click();
  expect(onEid).toHaveBeenCalledWith("E2");
});
