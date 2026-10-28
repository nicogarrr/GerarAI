import { expect, test } from "@playwright/test";
import { createHash, createHmac, randomUUID } from "node:crypto";

/**
 * Canario de aislamiento entre tenants contra la API real (E2E_RUN=1).
 * Dos tenants sinteticos firmados con la auth estricta: A crea objetos; B
 * intenta leer, editar y borrar cada uno por id. Nunca 2xx con datos de A y
 * nunca 5xx. Complementa data-engine/tests/test_tenant_release_matrix.py
 * (que cubre mas rutas sin servidor). Solo datos sinteticos y locales.
 */
const secret =
  process.env.RESEARCH_AUTH_SECRET ?? "cavaai-e2e-research-secret-at-least-32-characters";
const apiBaseURL = process.env.E2E_API_URL ?? "http://127.0.0.1:8101";
const runE2E = process.env.E2E_RUN === "1";
const suffix = randomUUID().slice(0, 8);
const MARKER = `TENANT-A-MARKER-${suffix}`;

if (runE2E) {
  const host = new URL(apiBaseURL).hostname;
  if (!["127.0.0.1", "localhost", "[::1]"].includes(host)) {
    throw new Error("El canario de aislamiento solo admite una API local aislada");
  }
}

type Who = "a" | "b";

function headers(who: Who, method: string, path: string, body: Buffer) {
  const tenant = `sec-${who}-${suffix}`;
  const user = `sec-user-${who}-${suffix}`;
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const nonce = randomUUID().replaceAll("-", "");
  const bodyHash = createHash("sha256").update(body).digest("hex");
  const signature = createHmac("sha256", secret)
    .update(`${tenant}:${user}:${timestamp}:${nonce}:${method}:${path}:${bodyHash}`)
    .digest("hex");
  return {
    "X-CavaAI-Tenant": tenant,
    "X-CavaAI-User": user,
    "X-CavaAI-Timestamp": timestamp,
    "X-CavaAI-Nonce": nonce,
    "X-CavaAI-Method": method,
    "X-CavaAI-Path": path,
    "X-CavaAI-Body-Hash": bodyHash,
    "X-CavaAI-Signature": signature,
    ...(body.length ? { "Content-Type": "application/json" } : {}),
  };
}

test.describe("tenant isolation canary", () => {
  test.skip(!runE2E, "Set E2E_RUN=1 to run API security tests.");

  async function call(
    request: import("@playwright/test").APIRequestContext,
    who: Who,
    method: string,
    path: string,
    data?: unknown,
  ) {
    const body = data === undefined ? Buffer.alloc(0) : Buffer.from(JSON.stringify(data));
    return request.fetch(new URL(path, apiBaseURL).toString(), {
      method,
      headers: headers(who, method, path, body),
      ...(data === undefined ? {} : { data: body }),
    });
  }

  function expectDenied(res: { status(): number }, text: string, what: string) {
    expect(res.status(), `${what}: no debe ser 5xx`).toBeLessThan(500);
    expect(res.status(), `${what}: B no puede tener exito`).toBeGreaterThanOrEqual(400);
    expect(text, `${what}: fuga de datos de A`).not.toContain(MARKER);
  }

  test("B cannot touch A's screen or collection", async ({ request }) => {
    const criterion = { left: "pe", operator: "<", right: "20" };
    const screen = await call(request, "a", "POST", "/api/screeners/screens", {
      name: `${MARKER} screen`,
      criteria: [criterion],
    });
    expect([200, 201]).toContain(screen.status());
    const screenId = (await screen.json()).id;

    const collection = await call(request, "a", "POST", "/api/knowledge/collections", {
      name: `${MARKER} col`,
    });
    expect([200, 201]).toContain(collection.status());
    const collectionId = (await collection.json()).id;

    const attacks: Array<[string, string, unknown?]> = [
      ["PUT", `/api/screeners/screens/${screenId}`, { name: "hijack", criteria: [criterion] }],
      ["POST", `/api/screeners/screens/${screenId}/run`],
      ["DELETE", `/api/screeners/screens/${screenId}`],
      ["DELETE", `/api/knowledge/collections/${collectionId}`],
    ];
    for (const [method, path, data] of attacks) {
      const res = await call(request, "b", method, path, data);
      expectDenied(res, await res.text(), `${method} ${path}`);
    }

    for (const path of ["/api/screeners/screens", "/api/knowledge/collections"]) {
      const listB = await call(request, "b", "GET", path);
      expect(await listB.text()).not.toContain(MARKER);
      const listA = await call(request, "a", "GET", path);
      expect(await listA.text()).toContain(MARKER);
    }
  });

  test("a forged tenant header with a foreign signature is rejected", async ({ request }) => {
    const path = "/api/screeners/screens";
    const forged = { ...headers("a", "GET", path, Buffer.alloc(0)), "X-CavaAI-Tenant": `sec-b-${suffix}` };
    const res = await request.fetch(new URL(path, apiBaseURL).toString(), { method: "GET", headers: forged });
    expect([401, 403]).toContain(res.status());
  });
});
