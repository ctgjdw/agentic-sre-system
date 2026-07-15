import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { GovernanceScreen } from "./GovernanceScreen";

afterEach(() => vi.unstubAllGlobals());

function mount() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: RequestInfo) => {
      if (String(url).includes("/audit"))
        return new Response(
          JSON.stringify({
            events: [
              {
                id: "e1", ts: "2026-07-11T14:22:04Z", case_id: "c1", actor: "alex.goh",
                event_type: "approval", payload: { gate: "rca", decision: "approve" },
              },
            ],
          }),
        );
      return new Response(
        JSON.stringify({
          paused: false, scm_draft_mr: false, running_cases: 1, cases_opened_24h: 9,
          agents: [{ agent: "rca", tier: "frontier", tools: [], usd_per_day: 6, spend_today: 4.2 }],
          suppression_24h: { dedup: 41, debounce: 22, grouped: 6 },
        }),
      );
    }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <GovernanceScreen />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("agent card shows spend vs cap and audit rows render", async () => {
  mount();
  expect(await screen.findByText(/\$4\.20 \/ \$6\.00 today/)).toBeInTheDocument();
  expect(screen.getByText(/approval/)).toBeInTheDocument();
  expect(screen.getByText(/deduped: 41/i)).toBeInTheDocument();
});
