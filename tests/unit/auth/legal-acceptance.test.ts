import { beforeEach, describe, expect, it, vi } from 'vitest';
import { memoryAdapter } from 'better-auth/adapters/memory';

vi.mock('@/database/mongoose', () => ({ connectToDatabase: vi.fn() }));
vi.mock('better-auth/next-js', () => ({ nextCookies: () => ({ id: 'test-next-cookies' }) }));
vi.mock('@/lib/auth/approval-notify', () => ({ notifyPendingAccount: vi.fn(async () => false) }));
vi.mock('@/database/models/account-approval.model', () => ({ AccountApproval: { create: vi.fn(async () => ({ _id: 'approval-test' })) } }));
vi.mock('@/lib/auth/email', () => ({ isPasswordResetEmailConfigured: () => false }));

import { createAuthInstance } from '@/lib/better-auth/auth';
import { hasLegalAcceptance, legalAcceptanceStamp, LEGAL_TEXT_VERSIONS } from '@/lib/auth/legal-acceptance';

const input = { name: 'New user', email: 'new@example.test', password: 'test-password-123', acceptTerms: true };
let records: Record<string, Array<Record<string, unknown>>>;
let auth: ReturnType<typeof createAuthInstance>;

async function request(path: string, body: unknown, cookie?: string) {
    return auth.handler(new Request(`http://localhost:3000/api/auth${path}`, {
        method: 'POST', headers: { 'content-type': 'application/json', origin: 'http://localhost:3000', ...(cookie ? { cookie } : {}) },
        body: JSON.stringify(body),
    }));
}

beforeEach(() => {
    records = { user: [], session: [], account: [], verification: [], rateLimit: [] };
    auth = createAuthInstance(memoryAdapter(records));
    vi.spyOn(console, 'warn').mockImplementation(() => {});
});

describe('signup legal acceptance through the real auth HTTP pipeline', () => {
    it.each([undefined, false, 'true', 1, null, {}, []])('rejects non-boolean acceptance %j without creating user or account', async (acceptTerms) => {
        const response = await request('/sign-up/email', { ...input, acceptTerms });
        expect(response.status).toBe(400);
        expect((await response.json()).code).toBe('LEGAL_ACCEPTANCE_REQUIRED');
        expect(records.user).toHaveLength(0);
        expect(records.account).toHaveLength(0);
    });

    it('stores server versions and server time in the same user creation', async () => {
        const started = Date.now();
        const response = await request('/sign-up/email', input);
        expect(response.status).toBe(200);
        expect(records.user).toHaveLength(1);
        const user = records.user[0];
        expect(user.termsVersion).toBe(LEGAL_TEXT_VERSIONS.terms);
        expect(user.privacyVersion).toBe(LEGAL_TEXT_VERSIONS.privacy);
        expect(new Date(user.legalAcceptedAt as string).getTime()).toBeGreaterThanOrEqual(started);
        expect(new Date(user.legalAcceptedAt as string).getTime()).toBeLessThanOrEqual(Date.now());
        expect(user.accountStatus).toBe('pending');
        expect(records.session).toHaveLength(0);
        expect(user).not.toHaveProperty('acceptTerms');
    });

    it.each(['termsVersion', 'privacyVersion', 'legalAcceptedAt'])('rejects a client-supplied %s', async (field) => {
        const response = await request('/sign-up/email', { ...input, [field]: 'forged' });
        expect(response.status).toBe(400);
        expect(records.user).toHaveLength(0);
    });

    it('internal creation is not backfilled as acceptance', async () => {
        const ctx = await auth.$context;
        const user = await ctx.internalAdapter.createUser({ email: 'internal@example.test', name: 'Internal' }, { method: 'email' });
        expect(user.legalAcceptedAt).toBeFalsy();
        expect(records.user[0].termsVersion).toBeFalsy();
    });

    it('old accounts can still log in without acceptance fields and cannot forge them on update', async () => {
        await request('/sign-up/email', input);
        const user = records.user[0];
        user.accountStatus = 'approved';
        delete user.termsVersion; delete user.privacyVersion; delete user.legalAcceptedAt;
        const login = await request('/sign-in/email', { email: input.email, password: input.password });
        expect(login.status).toBe(200);
        const cookie = login.headers.get('set-cookie')!;
        expect(cookie).toContain('session_token');
        const changed = await request('/update-user', { termsVersion: 'forged', privacyVersion: 'forged', legalAcceptedAt: new Date().toISOString() }, cookie);
        expect(changed.status).toBe(400);
        expect(user).not.toHaveProperty('legalAcceptedAt');
    });

    it('does not fabricate acceptance for an existing legacy account or overwrite it on duplicate signup', async () => {
        await request('/sign-up/email', input);
        const user = records.user[0];
        delete user.termsVersion; delete user.privacyVersion; delete user.legalAcceptedAt;
        const response = await request('/sign-up/email', input);
        expect(response.status).toBe(200);
        expect(records.user).toHaveLength(1);
        expect(user).not.toHaveProperty('legalAcceptedAt');
        expect(user).not.toHaveProperty('termsVersion');
    });
});

describe('strict legal acceptance helpers', () => {
    it.each([undefined, null, false, true, 'true', 1, [], {}, { acceptTerms: 'true' }])('does not coerce %j', (body) => {
        expect(hasLegalAcceptance(body)).toBe(false);
    });
    it('makes a fresh server stamp with content fingerprints and optional explicit clock', () => {
        const now = new Date('2026-11-11T19:00:00Z');
        expect(legalAcceptanceStamp(now).legalAcceptedAt).toBe(now);
        expect(LEGAL_TEXT_VERSIONS.terms).toMatch(/^sha256:[a-f0-9]{64}$/);
        expect(LEGAL_TEXT_VERSIONS.privacy).toMatch(/^sha256:[a-f0-9]{64}$/);
        expect(LEGAL_TEXT_VERSIONS.terms).not.toBe(LEGAL_TEXT_VERSIONS.privacy);
    });
});

describe('Lighthouse CI session script signup contract', () => {
    it('creates an explicitly consenting ephemeral account before approval, login and backend seeding', async () => {
        const mongoose = (await import('mongoose')).default;
        vi.stubEnv('CI', 'true');
        vi.stubEnv('LHCI_BASE_URL', 'http://localhost:3000');
        vi.stubEnv('LHCI_BACKEND_URL', 'http://127.0.0.1:8100');
        vi.stubEnv('MONGODB_URI', 'mongodb://127.0.0.1:27017/cavaai_lhci');
        vi.stubEnv('RESEARCH_AUTH_SECRET', 'local-lhci-contract-test-secret');
        vi.stubEnv('GITHUB_ENV', '');
        const connect = vi.spyOn(mongoose, 'connect').mockResolvedValue(mongoose);
        const disconnect = vi.spyOn(mongoose, 'disconnect').mockResolvedValue(undefined);
        const updateOne = vi.fn(async ({ email }, { $set }) => {
            const user = records.user.find((record) => record.email === email);
            expect(user?.termsVersion).toBe(LEGAL_TEXT_VERSIONS.terms);
            expect(user?.privacyVersion).toBe(LEGAL_TEXT_VERSIONS.privacy);
            expect(user?.legalAcceptedAt).toBeTruthy();
            Object.assign(user!, $set);
            return { matchedCount: 1 };
        });
        const originalDb = Object.getOwnPropertyDescriptor(mongoose.connection, 'db');
        Object.defineProperty(mongoose.connection, 'db', {
            configurable: true, value: { collection: () => ({ updateOne }) },
        });
        const statuses: number[] = [];
        const payloads: Record<string, unknown>[] = [];
        const fetchMock = vi.fn(async (url: string, options: RequestInit) => {
            if (url.startsWith('http://localhost:3000/api/auth/')) {
                payloads.push(JSON.parse(String(options.body)));
                const response = await auth.handler(new Request(url, options));
                statuses.push(response.status);
                return response;
            }
            expect(url).toMatch(/^http:\/\/127\.0\.0\.1:8100\/api\//);
            expect(records.session).toHaveLength(1);
            return new Response(null, { status: 200 });
        });
        vi.stubGlobal('fetch', fetchMock);
        vi.spyOn(console, 'log').mockImplementation(() => {});
        try {
            const script = '../../../scripts/lhci/session.mjs';
            await import(script);
            expect(statuses).toEqual([200, 200]);
            expect(payloads[0].acceptTerms).toBe(true);
            expect(connect).toHaveBeenCalledOnce();
            expect(updateOne).toHaveBeenCalledOnce();
            expect(disconnect).toHaveBeenCalledOnce();
            expect(fetchMock).toHaveBeenCalledTimes(13); // signup, login, 11 signed seeds
            expect(records.user).toHaveLength(1);
            expect(records.user[0].accountStatus).toBe('approved');
        } finally {
            if (originalDb) Object.defineProperty(mongoose.connection, 'db', originalDb);
            else Reflect.deleteProperty(mongoose.connection, 'db');
            vi.unstubAllEnvs();
            vi.unstubAllGlobals();
        }
    });
});
