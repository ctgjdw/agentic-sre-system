import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { ArtifactScreen } from "./ArtifactScreen";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

// Mirrors the real gateway Artifact JSON (no id/cost_usd; structured = RcaOut.model_dump()).
const DETAIL = {
  case: {
    id: "c1", display_id: "CASE-0142", kind: "incident", status: "waiting_approval",
    phase: "gate_rca", title: "Error spike", severity: 2, effort: "medium", round: 1,
    failure_class: null, spend_usd: 0.87, tokens_in: 0, tokens_out: 0, tool_calls: 0,
    halt_reason: null, created_at: "", updated_at: "", closed_at: null,
  },
  signals: [],
  approvals: [],
  hypotheses: [],
  evidence: [
    {
      eid: "E1", worker: "metrics", toolset: "prometheus", invocation: "q",
      excerpt: "18% at 14:02", source_url: null, observed_at: "", hypothesis_links: [],
    },
  ],
  artifacts: [
    {
      kind: "rca", version: 2, body_md: "## Immediate mitigation\nRevert PR #212",
      body_edited_md: null, model_id: "gemini-2.5-pro", created_at: "",
      structured: {
        mitigation_md: "Revert PR #212",
        causal_chain: [{ step: "PR #212", eids: ["E1"] }],
        blast_radius_md: "",
        timeline: [],
        alternatives: [],
        monitoring_gaps_md: "",
        claims: [{ text: "spike at 14:02", eids: ["E1"] }],
        confidence: 0.81,
      },
      verification: { verified: true, checked: 1, failures: [] },
    },
  ],
};

function mount() {
  const fetchMock = vi.fn(async (url: RequestInfo, init?: RequestInit) => {
    void init;
    const path = String(url);
    if (path.includes("/decision")) return new Response("{}");
    if (path.includes("/governance"))
      return new Response(
        JSON.stringify({
          paused: false, scm_draft_mr: false, running_cases: 0, agents: [],
          suppression_24h: {}, cases_opened_24h: 0,
        }),
      );
    return new Response(JSON.stringify(DETAIL));
  });
  vi.stubGlobal("fetch", fetchMock);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/cases/c1/artifact/rca"]}>
        <Routes>
          <Route path="/cases/:id/artifact/:kind" element={<ArtifactScreen />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return fetchMock;
}

test("shows verification badge, outcome preview, posts approve decision", async () => {
  localStorage.setItem("reviewer", "alex.goh");
  const fetchMock = mount();
  expect(await screen.findByText(/citations verified 1\/1/)).toBeInTheDocument();
  expect(screen.getByText(/publishes this RCA/i)).toBeInTheDocument();
  expect(screen.getByText(/does not change any system/i)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /^approve$/i }));
  const call = fetchMock.mock.calls.find(([u]) => String(u).includes("/decision"))!;
  expect(JSON.parse(String(call[1]!.body))).toMatchObject({
    gate: "rca",
    decision: "approve",
    decided_by: "alex.goh",
  });
});
