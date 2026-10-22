/** Actual server action/client; synthetic identity and HTTP fixtures only. */
import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
register('./research-client-contract.loader.mjs', import.meta.url);
// @ts-expect-error TS5097: Node strip-types needs explicit extension.
const { chatWithPortfolio } = await import('../lib/actions/brain.actions.ts');
const realFetch = globalThis.fetch;
after(() => { globalThis.fetch = realFetch; });

for (const [status, message] of [
    [429, /demasiadas consultas.*Reinténtalo/i],
    [502, /no está disponible.*Reinténtalo/i],
    [503, /no está disponible.*Reinténtalo/i],
    [504, /tarda más de lo normal.*Reinténtalo/i],
] as const) {
    test(`HTTP ${status} becomes an honest recoverable Spanish result`, async () => {
        globalThis.fetch = (async () => new Response(JSON.stringify({ detail: 'PRIVATE diagnostic' }), {
            status, headers: { 'Content-Type': 'application/json' },
        })) as typeof fetch;
        const result = await chatWithPortfolio('Que es el PER?', 'contract-test-user');
        assert.equal(result.success, false);
        assert.match(result.message, message);
        assert.doesNotMatch(result.message, /PRIVATE|diagnostic|sin datos/i);
        assert.deepEqual(result.citations, []);
    });
}

for (const status of [401, 403, 400, 422]) {
    test(`HTTP ${status} is not hidden by availability fallback`, async () => {
        globalThis.fetch = (async () => new Response(JSON.stringify({ detail: 'Denied' }), {
            status, headers: { 'Content-Type': 'application/json' },
        })) as typeof fetch;
        await assert.rejects(chatWithPortfolio('Que es el PER?', 'contract-test-user'),
            (error: unknown) => !!error && typeof error === 'object' && 'statusCode' in error && error.statusCode === status);
    });
}
