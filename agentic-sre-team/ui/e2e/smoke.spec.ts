import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, request as pwRequest, test } from "@playwright/test";

const GATEWAY = process.env.SMOKE_GATEWAY ?? "http://localhost:8080";
const fixturePath = fileURLToPath(
  new URL("../../gateway/tests/fixtures/grafana_webhook.json", import.meta.url),
);

// `compose up -d` returns before the gateway finishes booting (alembic upgrade + uvicorn),
// so poll healthz before the smoke fires rather than racing a cold container.
test.beforeAll(async () => {
  const ctx = await pwRequest.newContext();
  for (let i = 0; i < 60; i++) {
    try {
      const r = await ctx.get(`${GATEWAY}/api/healthz`);
      if (r.ok()) break;
    } catch {
      /* not up yet */
    }
    await new Promise((res) => setTimeout(res, 1000));
  }
  await ctx.dispose();
});

// Full operator loop on the fake profile: a Grafana alert opens a case, the queue
// surfaces it, and the two gates are approved from the console until the case closes.
test("alert -> queue -> detail -> approve RCA -> approve runbook -> closed", async ({ page, request }) => {
  const fixture = JSON.parse(readFileSync(fixturePath, "utf8"));
  // Fresh label fingerprint each run so intake opens a new case (the partial-unique
  // index rejects a second open case with the same fingerprint).
  fixture.alerts[0].labels.alertname = `E2E-${Date.now()}`;

  const res = await request.post(`${GATEWAY}/api/webhooks/grafana`, { data: fixture });
  expect(res.ok()).toBeTruthy();

  // Approvals prompt for reviewer identity + (on reject) a reason via window.prompt.
  page.on("dialog", (d) => d.accept("e2e"));

  await page.goto("/cases");
  await page.getByRole("link", { name: /review rca/i }).first().click({ timeout: 90_000 });
  await expect(page.getByText(/citations verified/i)).toBeVisible();
  await page.getByRole("button", { name: /^approve$/i }).click();

  await page.goto("/cases");
  await page.getByRole("link", { name: /review runbook/i }).first().click({ timeout: 90_000 });
  // The runbook does not go through the citation-verify node, so it has no verification
  // badge; wait for its Approve button to be enabled (case is waiting at gate_runbook).
  const runbookApprove = page.getByRole("button", { name: /^approve$/i });
  await expect(runbookApprove).toBeEnabled({ timeout: 90_000 });
  await runbookApprove.click();

  await page.goto("/cases");
  await page.getByRole("button", { name: /closed/i }).click();
  await expect(page.getByText(/CASE-/).first()).toBeVisible();
});
