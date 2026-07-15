import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { QueueScreen } from "./QueueScreen";

afterEach(() => vi.unstubAllGlobals());

const CASES = {
  cases: [
    {
      id: "c1", display_id: "CASE-0142", kind: "incident", status: "waiting_approval",
      phase: "gate_rca", title: "Error rate spike on admin-server", severity: 2,
      effort: "medium", round: 1, failure_class: null, spend_usd: 0.87, tokens_in: 0,
      tokens_out: 0, tool_calls: 0, halt_reason: null, created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(), closed_at: null,
    },
    {
      id: "c2", display_id: "CASE-0139", kind: "pipeline_failure", status: "open",
      phase: "ci_worker", title: "CI failing: test job on main", severity: 3,
      effort: "medium", round: 1, failure_class: "flaky", spend_usd: 0.09, tokens_in: 0,
      tokens_out: 0, tool_calls: 0, halt_reason: null, created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(), closed_at: null,
    },
  ],
};

function mount() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: RequestInfo) => {
      const path = String(url);
      if (path.startsWith("/api/cases")) return new Response(JSON.stringify(CASES));
      if (path.startsWith("/api/activity"))
        return new Response(JSON.stringify({ buckets: [], cases: [], annotations: [] }));
      return new Response(JSON.stringify({ status: "ok", service: "sre-gateway", components: {} }));
    }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <QueueScreen />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("needs-you tab is default and shows the waiting case with its action", async () => {
  mount();
  expect(await screen.findByText("CASE-0142")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /review rca/i })).toHaveAttribute(
    "href",
    "/cases/c1/artifact/rca",
  );
  expect(screen.queryByText("CASE-0139")).not.toBeInTheDocument(); // active tab only
});

test("pipeline case shows kind badge and failure class on the active tab", async () => {
  mount();
  await userEvent.click(await screen.findByRole("button", { name: /active/i }));
  expect(await screen.findByText("PIPELINE")).toBeInTheDocument();
  expect(screen.getByText(/class: flaky/i)).toBeInTheDocument();
});
