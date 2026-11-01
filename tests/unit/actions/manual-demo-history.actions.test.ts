import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requireAuthenticatedUser, connectToDatabase, tradeFind } = vi.hoisted(() => ({
    requireAuthenticatedUser: vi.fn(),
    connectToDatabase: vi.fn(async () => ({})),
    tradeFind: vi.fn(),
}));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));
vi.mock('@/database/mongoose', () => ({ connectToDatabase }));
vi.mock('@/lib/paper-trading/accounting', () => ({ computeManualDemoAccount: vi.fn() }));
vi.mock('@/lib/paper-trading/ledger-adapter', () => ({ docsToLedger: vi.fn(() => ({ entries: [], violations: [] })) }));
vi.mock('@/lib/market/quote-cache', () => ({
    createQuoteCache: () => ({ getQuote: vi.fn() }),
    combineAbortSignals: (s: AbortSignal) => s,
}));
vi.mock('@/lib/market/quote-freshness', () => ({ sanitizeFinnhubQuote: (q: unknown) => q }));
vi.mock('@/database/models/manual-demo.model', () => ({
    MANUAL_DEMO_STARTING_CASH_EUR: 100000,
    ManualDemoTrade: { find: tradeFind },
}));

import { Types } from 'mongoose';
import { getManualDemoHistory } from '@/lib/actions/manual-demo.actions';

const doc = (id: string, createdAtMs: number) => ({
    _id: new Types.ObjectId(id.padEnd(24, '0').slice(0, 24)),
    clientOrderId: `orden-${id}`, kind: 'accion', symbol: 'AAPL', name: 'Apple',
    side: 'buy', openClose: 'open', quantity: 1, status: 'filled', fillPrice: 100,
    currency: 'EUR', fee: 0, executedAt: new Date(createdAtMs), rejectReason: null,
    createdAt: new Date(createdAtMs),
});

let capturedFilter: unknown;
let capturedLimit: number | null;
const seedFind = (docs: unknown[]) => {
    tradeFind.mockImplementation((filter: unknown) => {
        capturedFilter = filter;
        return {
            sort: () => ({
                limit: (n: number) => { capturedLimit = n; return Promise.resolve(docs); },
            }),
        };
    });
};

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    requireAuthenticatedUser.mockResolvedValue({ id: 'user-1' });
    capturedFilter = undefined;
    capturedLimit = null;
});

describe('autorización en toda página', () => {
    it('sin sesión -> fallo legible sin consultar', async () => {
        requireAuthenticatedUser.mockRejectedValue(Object.assign(new Error('x'), { name: 'AuthenticationError' }));
        expect(await getManualDemoHistory()).toEqual({ ok: false, message: 'Inicia sesión para usar la cuenta demo.' });
        expect(tradeFind).not.toHaveBeenCalled();
    });

    it('el filtro lleva SIEMPRE el userId de la sesión, también con cursor', async () => {
        seedFind([]);
        await getManualDemoHistory({ before: '1777000000000:abcdef0123456789abcdef01' });
        expect(capturedFilter).toMatchObject({ userId: 'user-1' });
    });
});

describe('cursor y límite', () => {
    it.each(['no-es-cursor', '1777000000000', ':abc', '0:abc', '1777000000000:', '9999999999999999:x'])(
        'cursor %s -> rechazado, no reinterpretado', async (before) => {
            expect(await getManualDemoHistory({ before })).toMatchObject({ ok: false, field: 'before' });
            expect(tradeFind).not.toHaveBeenCalled();
        },
    );

    it('cursor ObjectId reconstruye el tipo para el desempate BSON', async () => {
        seedFind([]);
        await getManualDemoHistory({ before: '1777000000000:abcdef0123456789abcdef01' });
        const f = capturedFilter as { $or: Array<{ createdAt: unknown; _id?: { $lt: unknown } }> };
        expect(f.$or[0].createdAt).toEqual({ $lt: new Date(1777000000000) });
        expect(f.$or[1]._id?.$lt).toBeInstanceOf(Types.ObjectId);
    });

    it('cursor con id no-ObjectId se usa como cadena', async () => {
        seedFind([]);
        await getManualDemoHistory({ before: '1777000000000:idem-key' });
        const f = capturedFilter as { $or: Array<{ _id?: { $lt: unknown } }> };
        expect(f.$or[1]._id?.$lt).toBe('idem-key');
    });

    it('límite: default 200, tope 500, se pide limit+1 para hasMore', async () => {
        seedFind([]);
        await getManualDemoHistory();
        expect(capturedLimit).toBe(201);
        await getManualDemoHistory({ limit: 99999 });
        expect(capturedLimit).toBe(501);
        await getManualDemoHistory({ limit: '50' });
        expect(capturedLimit).toBe(51);
        await getManualDemoHistory({ limit: 'no-numero' });
        expect(capturedLimit).toBe(201);
    });

    it('página completa -> hasMore con cursor del último row; página corta -> hasMore false', async () => {
        seedFind([doc('1', 3000), doc('2', 2000), doc('3', 1000)]);
        const page = await getManualDemoHistory({ limit: 2 });
        expect(page).toMatchObject({ ok: true, hasMore: true });
        expect((page as { orders: unknown[] }).orders).toHaveLength(2);
        expect((page as { nextBefore: string }).nextBefore).toMatch(/^2000:/);
        seedFind([doc('3', 1000)]);
        expect(await getManualDemoHistory({ before: '2000:abc', limit: 2 })).toMatchObject({ ok: true, hasMore: false, nextBefore: null });
    });
});

describe('robustez', () => {
    it('entrada no objeto -> página por defecto', async () => {
        seedFind([]);
        expect(await getManualDemoHistory('cualquier cosa')).toMatchObject({ ok: true, orders: [] });
    });

    it('mongo caído -> fallo genérico sin filtrar el error interno', async () => {
        tradeFind.mockImplementation(() => { throw new Error('mongo caído'); });
        expect(await getManualDemoHistory()).toMatchObject({ ok: false, message: expect.stringContaining('Inténtalo de nuevo') });
    });
});
