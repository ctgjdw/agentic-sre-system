import { render, screen, within } from "@testing-library/react";
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

// Workers are unguarded and emit NO node_start/node_end - the ledger must synthesize a
// per-worker entry from the tool_call/worker_warning stream, keyed by `worker`, and NOT
// dump every worker's tools onto the Plan entry.
test("builds a per-worker entry from tool_call events and closes it on node_update", () => {
  render(
    <Ledger
      events={[
        { type: "plan", workers: ["metrics_worker", "logs_worker"], effort: "medium", round: 1 },
        {
          type: "tool_call", worker: "metrics", phase: "tool_result",
          tool_name: "prometheus_query_range", toolset: "prometheus", description: "p95 by route",
        },
        {
          type: "tool_call", worker: "logs", phase: "tool_result",
          tool_name: "loki_query", toolset: "loki", description: "error logs in window",
        },
        { type: "node_update", node: "metrics_worker", keys: ["evidence"] },
      ]}
    />,
  );
  // Distinct worker entries exist (not folded into Plan).
  const metrics = screen.getByText(/^Metrics worker/).closest("div")!;
  const logs = screen.getByText(/^Logs worker/).closest("div")!;
  expect(metrics).toBeInTheDocument();
  expect(logs).toBeInTheDocument();
  // Each worker owns its own tool line.
  expect(within(metrics).getByText(/holmes:prometheus/)).toBeInTheDocument();
  expect(within(logs).getByText(/holmes:loki/)).toBeInTheDocument();
  // metrics closed on node_update (no data-live); logs still running (data-live present).
  expect(metrics.hasAttribute("data-live")).toBe(false);
  expect(logs.getAttribute("data-live")).toBe("true");
});
