import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { Ledger } from "./Ledger";

test("groups events into node entries with tool lines", () => {
  render(
    <Ledger
      events={[
        { type: "node_start", node: "triage" },
        { type: "node_end", node: "triage" },
        { type: "plan", workers: ["metrics_worker", "logs_worker"], effort: "medium", round: 1 },
        { type: "node_start", node: "synthesize" },
        {
          type: "tool_call", worker: "metrics", phase: "tool_result",
          tool_name: "prometheus_query_range", toolset: "prometheus",
          description: "p95 by route via Kong",
        },
      ]}
    />,
  );
  expect(screen.getByText(/Triage/)).toBeInTheDocument();
  expect(screen.getByText(/fan-out: metrics_worker, logs_worker/i)).toBeInTheDocument();
  expect(screen.getByText(/holmes:prometheus/)).toBeInTheDocument();
  expect(screen.getByText(/synthesize/i).closest("[data-live]")).toBeTruthy();
});
