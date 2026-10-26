/**
 * Contrato de research: timeout configurable y degradación independiente.
 *
 * Ejecución: node --experimental-strip-types --test scripts/research-client-contract.test.ts
 * No toca la red: fetch, identidad y OpenAPI se sustituyen por stubs locales.
 */
import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

register('./research-client-contract.loader.mjs', import.meta.url);

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
const { researchRequest, researchTimeoutFor, RESEARCH_TIMEOUTS } = await import('../lib/research/client.ts');
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
const { getResearchThesisWorkspace } = await import('../lib/actions/research.actions.ts');

const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function restoreEnv(): void {
  for (const key of ['FMP_BACKEND_URL', 'RESEARCH_AUTH_SECRET']) {
    if (originalEnv[key] === undefined) delete process.env[key];
    else process.env[key] = originalEnv[key];
  }
}

describe('researchRequest: timeout configurable', () => {
  beforeEach(() => {
    process.env.FMP_BACKEND_URL = 'http://127.0.0.1:8001';
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    restoreEnv();
  });

  it('usa el timeout global sensato por defecto (15s)', async () => {
    let seenSignal: AbortSignal | undefined;
    globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      seenSignal = init?.signal as AbortSignal;
      return jsonResponse({ ok: true });
    }) as typeof fetch;

    await researchRequest<{ ok: boolean }>('/api/contract');
    assert.ok(seenSignal, 'debe enviar AbortSignal');
    assert.equal(RESEARCH_TIMEOUTS.GLOBAL_MS, 15_000);
    assert.equal(RESEARCH_TIMEOUTS.GET_FAST_MS, 8_000);
    assert.equal(RESEARCH_TIMEOUTS.INSIDER_SCAN_MS, 30_000);
    assert.equal(researchTimeoutFor('/api/insider/signals?ticker=MSFT', 'GET', { fast: true }), 30_000);
  });

  it('respeta timeout explícito y el signal externo', async () => {
    const signals: AbortSignal[] = [];
    globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      signals.push(init?.signal as AbortSignal);
      return jsonResponse({ ok: true });
    }) as typeof fetch;
    const external = new AbortController().signal;
    await researchRequest('/api/contract', { signal: external, timeoutMs: 1 });
    assert.notEqual(signals[0], external);
    assert.equal(signals[0]?.aborted, false);
    assert.equal(researchTimeoutFor('/api/contract', 'GET', { timeoutMs: 1 }), 1);
  });

  it('convierte un timeout en mensaje de reintento accionable', async () => {
    globalThis.fetch = (async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
      throw new DOMException('The operation was aborted due to timeout', 'TimeoutError');
    }) as typeof fetch;

    await assert.rejects(
      researchRequest('/api/contract', { timeoutMs: 1 }),
      /timeout de 1 ms.*reintenta en unos segundos/,
    );
  });

  it('usa 8s por defecto en GET de home/portfolio y permite override', async () => {
    let seenSignal: AbortSignal | undefined;
    globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      seenSignal = init?.signal as AbortSignal;
      return jsonResponse({ ok: true });
    }) as typeof fetch;
    await researchRequest('/api/market/indices', { fast: true });
    assert.ok(seenSignal?.aborted === false);
    assert.equal(RESEARCH_TIMEOUTS.GET_FAST_MS, 8_000);
  });
});

describe('getResearchThesisWorkspace: fallos opcionales no tumban el workspace', () => {
  beforeEach(() => {
    process.env.FMP_BACKEND_URL = 'http://127.0.0.1:8001';
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    restoreEnv();
  });

  it('degrada con partial y conserva los endpoints que sí respondieron', async () => {
    const calls: string[] = [];
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const path = new URL(String(input)).pathname;
      calls.push(path);
      if (path.endsWith('/red-team/latest')) {
        throw new Error('optional fetch timed out');
      }
      if (path.endsWith('/latest')) return jsonResponse({ id: 7, thesis_markdown: 'Tesis' });
      if (path.endsWith('/versions')) return jsonResponse([{ id: 7 }]);
      if (path.endsWith('/sections')) return jsonResponse([{ id: 1 }]);
      if (path.endsWith('/graph')) return jsonResponse({ nodes: [], edges: [] });
      if (path.includes('/memory/claims')) return jsonResponse([{ id: 2 }]);
      return jsonResponse({ count: 0, history: [] });
    }) as typeof fetch;

    const result = await getResearchThesisWorkspace('AAPL');
    assert.equal(result.partial, true);
    assert.ok(result.errors?.length && result.errors.some((entry) => entry.includes('red-team')));
    assert.equal(result.thesis?.id, 7);
    assert.equal(result.history.length, 1);
    assert.equal(calls.length, 7);
  });
});
