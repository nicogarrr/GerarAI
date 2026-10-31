import { createHash, createHmac } from 'node:crypto';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ user: vi.fn() }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: mocks.user }));

import {
    normalizeResearchBody, researchIdentityHeaders, researchRequestPath,
} from '@/lib/auth/research-identity';

afterEach(() => { vi.unstubAllEnvs(); mocks.user.mockReset(); });

describe('researchRequestPath', () => {
    it('keeps only the decoded pathname, dropping the query string', () => {
        expect(researchRequestPath('https://engine.local/api/research/SAN.MC?fields=all')).toBe('/api/research/SAN.MC');
        expect(researchRequestPath('/api/research/SAN.MC?x=1')).toBe('/api/research/SAN.MC');
    });
    it('decodes percent-encoded tickers the way the data engine sees them', () => {
        // ^GSPC llega como %5EGSPC; el motor ve request.url.path decodificado.
        expect(researchRequestPath('/api/research/%5EGSPC')).toBe('/api/research/^GSPC');
    });
    it('keeps the encoded path when decoding fails or is not printable ASCII', () => {
        expect(researchRequestPath('/api/%E0%A4%A')).toBe('/api/%E0%A4%A'); // secuencia invalida
        expect(researchRequestPath('/api/%E2%82%AC')).toBe('/api/%E2%82%AC'); // euro: no ASCII
    });
    it('accepts a bare path without URL parsing', () => {
        expect(researchRequestPath('/api/research')).toBe('/api/research');
    });
});

describe('normalizeResearchBody', () => {
    it('passes through null/undefined, strings and ArrayBuffers', async () => {
        await expect(normalizeResearchBody(null)).resolves.toEqual({});
        await expect(normalizeResearchBody('{"a":1}')).resolves.toEqual({ body: '{"a":1}' });
        const buf = new Uint8Array([1, 2, 3]).buffer;
        await expect(normalizeResearchBody(buf)).resolves.toEqual({ body: buf });
        const u8 = new Uint8Array([4, 5, 6]);
        const r = await normalizeResearchBody(u8);
        expect(new Uint8Array(r.body as ArrayBuffer)).toEqual(u8);
    });
    it('serializes URLSearchParams once so the signed hash matches the sent bytes', async () => {
        const r = await normalizeResearchBody(new URLSearchParams({ a: '1', b: '2' }));
        expect(r.contentType).toContain('application/x-www-form-urlencoded');
        expect(new TextDecoder().decode(r.body as ArrayBuffer)).toBe('a=1&b=2');
    });
    it('serializes FormData with a single boundary and its content type', async () => {
        const form = new FormData();
        form.set('ticker', 'SAN.MC');
        const r = await normalizeResearchBody(form);
        expect(r.contentType).toContain('multipart/form-data; boundary=');
        expect(new TextDecoder().decode(r.body as ArrayBuffer)).toContain('SAN.MC');
    });
});

describe('researchIdentityHeaders', () => {
    const SECRET = 's'.repeat(32);
    it('fails closed when the secret is missing or too short', async () => {
        vi.stubEnv('RESEARCH_AUTH_SECRET', '');
        await expect(researchIdentityHeaders({ method: 'get', path: '/x' })).rejects.toMatchObject({ code: 'RESEARCH_AUTH_NOT_CONFIGURED' });
        vi.stubEnv('RESEARCH_AUTH_SECRET', 'short');
        await expect(researchIdentityHeaders({ method: 'get', path: '/x' })).rejects.toMatchObject({ code: 'RESEARCH_AUTH_NOT_CONFIGURED' });
    });
    it('signs tenant:user:timestamp:nonce:method:path:bodyHash with HMAC-SHA256', async () => {
        vi.stubEnv('RESEARCH_AUTH_SECRET', SECRET);
        mocks.user.mockResolvedValue({ id: 'user-1' });
        const h = await researchIdentityHeaders({ method: 'post', path: '/api/research/%5EGSPC?x=1', body: '{"q":1}' });
        expect(h['X-CavaAI-User']).toBe('user-1');
        expect(h['X-CavaAI-Tenant']).toBe('user-1');
        expect(h['X-CavaAI-Method']).toBe('POST');
        expect(h['X-CavaAI-Path']).toBe('/api/research/^GSPC');
        const expectedHash = createHash('sha256').update('{"q":1}', 'utf8').digest('hex');
        expect(h['X-CavaAI-Body-Hash']).toBe(expectedHash);
        const expectedSig = createHmac('sha256', SECRET)
            .update(`user-1:user-1:${h['X-CavaAI-Timestamp']}:${h['X-CavaAI-Nonce']}:POST:/api/research/^GSPC:${expectedHash}`)
            .digest('hex');
        expect(h['X-CavaAI-Signature']).toBe(expectedSig);
        expect(h['X-CavaAI-Nonce']).toMatch(/^[0-9a-f]{32}$/);
    });
    it('a tampered body or a different method produces a different signature', async () => {
        vi.stubEnv('RESEARCH_AUTH_SECRET', SECRET);
        mocks.user.mockResolvedValue({ id: 'user-1' });
        const a = await researchIdentityHeaders({ method: 'post', path: '/x', body: '{"q":1}' });
        const b = await researchIdentityHeaders({ method: 'post', path: '/x', body: '{"q":2}' });
        const c = await researchIdentityHeaders({ method: 'get', path: '/x', body: '{"q":1}' });
        expect(a['X-CavaAI-Signature']).not.toBe(b['X-CavaAI-Signature']);
        expect(a['X-CavaAI-Signature']).not.toBe(c['X-CavaAI-Signature']);
    });
    it('hashes Uint8Array bodies by their exact bytes', async () => {
        vi.stubEnv('RESEARCH_AUTH_SECRET', SECRET);
        mocks.user.mockResolvedValue({ id: 'user-1' });
        const bytes = new Uint8Array([10, 20, 30]);
        const h = await researchIdentityHeaders({ method: 'post', path: '/x', body: bytes });
        expect(h['X-CavaAI-Body-Hash']).toBe(createHash('sha256').update(bytes).digest('hex'));
    });
    it('uses a fresh nonce per call (anti-replay)', async () => {
        vi.stubEnv('RESEARCH_AUTH_SECRET', SECRET);
        mocks.user.mockResolvedValue({ id: 'user-1' });
        const a = await researchIdentityHeaders({ method: 'get', path: '/x' });
        const b = await researchIdentityHeaders({ method: 'get', path: '/x' });
        expect(a['X-CavaAI-Nonce']).not.toBe(b['X-CavaAI-Nonce']);
    });
});
