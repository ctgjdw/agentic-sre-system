import { afterEach, expect, test, vi } from "vitest";
import { api } from "./client";

afterEach(() => vi.unstubAllGlobals());

test("api returns parsed json", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ok: 1 }))));
  expect(await api<{ ok: number }>("/api/healthz")).toEqual({ ok: 1 });
});

test("api throws on http error with body detail", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ detail: "bad gate" }), { status: 409 })),
  );
  await expect(api("/api/x")).rejects.toThrow(/bad gate/);
});

test("api falls back to statusText when body is not json", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("<html>oops</html>", { status: 502, statusText: "Bad Gateway" })),
  );
  await expect(api("/api/x")).rejects.toThrow(/502: Bad Gateway/);
});
