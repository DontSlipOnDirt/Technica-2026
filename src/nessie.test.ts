import assert from "node:assert/strict";
import test from "node:test";
import { NessieApiError, NessieClient } from "./nessie.js";

test("NessieClient adds the API key and decodes JSON responses", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";

  globalThis.fetch = async (input) => {
    requestedUrl = String(input);
    return new Response(JSON.stringify([{ id: "account-1" }]), { status: 200 });
  };

  try {
    const client = new NessieClient({ apiKey: "test-key", baseUrl: "https://example.test/" });
    const accounts = await client.get<{ id: string }[]>("/customers/customer-1/accounts");
    assert.deepEqual(accounts, [{ id: "account-1" }]);
    assert.equal(requestedUrl, "https://example.test/customers/customer-1/accounts?key=test-key");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("NessieClient exposes HTTP failures without leaking response details", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response("upstream failure", { status: 500 });

  try {
    const client = new NessieClient({ apiKey: "test-key", baseUrl: "https://example.test" });
    await assert.rejects(
      client.get("/accounts/account-1"),
      (error: unknown) => error instanceof NessieApiError && error.status === 500,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("NessieClient supports PUT and DELETE requests", async () => {
  const originalFetch = globalThis.fetch;
  const methods: string[] = [];
  globalThis.fetch = async (_input, init) => {
    methods.push(init?.method ?? "GET");
    return new Response(JSON.stringify({ ok: true }), { status: 200 });
  };

  try {
    const client = new NessieClient({ apiKey: "test-key", baseUrl: "https://example.test" });
    await client.put("/customers/customer-1", { firstName: "Ada" });
    await client.delete("/customers/customer-1");
    assert.deepEqual(methods, ["PUT", "DELETE"]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});