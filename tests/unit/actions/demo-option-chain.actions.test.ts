import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requireAuthenticatedUser, cacheGetChain } = vi.hoisted(() => ({
    requireAuthenticatedUser: vi.fn<(...args: any[]) => any>(),
    cacheGetChain: vi.fn<(...args: any[]) => any>(),
}));

vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));
vi.mock('@/lib/market/cboe-chain-cache', () => ({ sharedCboeChainCache: { getChain: cacheGetChain } }));

import { getDemoOptionChain } from '@/lib/actions/demo-option-chain.actions';

// Tope de vencimientos de la respuesta (constante interna de la acción).
const MAX_CHAIN_EXPIRIES = 8;

type Premium = { lastTradePrice: number | null; lastTradeTime: string | null };
const attempt = (chain: Map<string, Premium> | null, over: object = {}) => ({
    chain,
    fetchFailed: false,
    retryAfterSeconds: null,
    fetchedAt: 1_763_000_000_000,
    saturated: false,
    ...over,
});
const trade = (price: number): Premium => ({ lastTradePrice: price, lastTradeTime: '2026-11-17T15:47:12' });
const noTrade: Premium = { lastTradePrice: null, lastTradeTime: null };

beforeEach(() => {
    vi.resetAllMocks();
    requireAuthenticatedUser.mockResolvedValue({ id: 'u1', email: 'u@test.dev', name: 'U' });
});

describe('getDemoOptionChain', () => {
    it('exige sesión antes de consultar la fuente', async () => {
        requireAuthenticatedUser.mockRejectedValue(new Error('no session'));
        expect(await getDemoOptionChain('AAPL')).toEqual({ ok: false, reason: 'noAuth' });
        expect(cacheGetChain).not.toHaveBeenCalled();
    });

    it.each([undefined, 42, '', '   ', 'AA PL', 'AAPL;DROP', 'SIMBOLODEMASIADOLARGO'])(
        'rechaza símbolo inválido %j sin tocar la fuente', async (symbol) => {
            expect(await getDemoOptionChain(symbol)).toEqual({ ok: false, reason: 'invalidSymbol' });
            expect(cacheGetChain).not.toHaveBeenCalled();
        },
    );

    it('normaliza el símbolo (minúsculas y raíz con punto)', async () => {
        cacheGetChain.mockResolvedValue(attempt(new Map([['BRK.B|2026-12-18|call|450000', trade(3.1)]])));
        const result = await getDemoOptionChain('  brk.b ');
        expect(cacheGetChain).toHaveBeenCalledWith('BRK.B');
        expect(result).toMatchObject({ ok: true, underlying: 'BRK.B' });
    });

    it('saturación local de la caché -> reason saturated', async () => {
        cacheGetChain.mockResolvedValue(attempt(null, { saturated: true }));
        expect(await getDemoOptionChain('AAPL')).toEqual({ ok: false, reason: 'saturated' });
    });

    it.each([
        ['fetch fallido', attempt(null, { fetchFailed: true })],
        ['cadena null', attempt(null)],
        ['fetchedAt null', attempt(new Map(), { fetchedAt: null })],
    ])('fuente no disponible (%s) -> reason source-unavailable', async (_label, value) => {
        cacheGetChain.mockResolvedValue(value);
        expect(await getDemoOptionChain('AAPL')).toEqual({ ok: false, reason: 'sourceUnavailable' });
    });

    it('cadena vacía -> not-covered (nunca se inventan strikes)', async () => {
        cacheGetChain.mockResolvedValue(attempt(new Map()));
        expect(await getDemoOptionChain('SAN')).toEqual({ ok: false, reason: 'notCovered' });
    });

    it('agrupa por vencimiento/strike, ordena y etiqueta solo operaciones reales', async () => {
        const chain = new Map<string, Premium>([
            ['ASTS|2026-12-18|call|50000', trade(5.05)],
            ['ASTS|2026-11-20|put|45000', noTrade],
            ['ASTS|2026-11-20|call|47500', trade(2.3)],
            ['ASTS|2026-11-20|call|45000', trade(3.9)],
            ['ASTS|2026-11-20|call|abc', trade(1)], // strike no numérico: fuera
            ['ASTS|2026-11-20|strangle|45000', trade(1)], // clave no call/put: fuera
            ['ASTS|2026-11-20|call', trade(1)], // clave malformada: fuera
        ]);
        cacheGetChain.mockResolvedValue(attempt(chain));
        const result = await getDemoOptionChain('ASTS');
        expect(result).toMatchObject({ ok: true, underlying: 'ASTS', fetchedAt: 1_763_000_000_000 });
        if (!result.ok) throw new Error('expected ok');
        expect(result.expiries.map((e) => e.expiry)).toEqual(['2026-11-20', '2026-12-18']);
        const nov = result.expiries[0];
        expect(nov.strikes.map((r) => r.strike)).toEqual([45, 47.5]);
        expect(nov.strikes[0]).toEqual({ strike: 45, call: { price: 3.9, time: '2026-11-17T15:47:12' }, put: null });
        expect(nov.strikes[1].call).toEqual({ price: 2.3, time: '2026-11-17T15:47:12' });
    });

    it(`limita la respuesta a los ${MAX_CHAIN_EXPIRIES} vencimientos más próximos`, async () => {
        const chain = new Map<string, Premium>();
        for (let i = 1; i <= 12; i += 1) {
            const expiry = `2027-${String(i).padStart(2, '0')}-15`;
            chain.set(`AAPL|${expiry}|call|150000`, trade(10));
        }
        cacheGetChain.mockResolvedValue(attempt(chain));
        const result = await getDemoOptionChain('AAPL');
        if (!result.ok) throw new Error('expected ok');
        expect(result.expiries).toHaveLength(MAX_CHAIN_EXPIRIES);
        expect(result.expiries[0].expiry).toBe('2027-01-15');
        expect(result.expiries.at(-1)?.expiry).toBe('2027-08-15');
    });

    it('precio sin hora (u hora sin precio) NO es referencia: queda null', async () => {
        const chain = new Map<string, Premium>([
            ['AAPL|2026-12-18|call|150000', { lastTradePrice: 10, lastTradeTime: null }],
            ['AAPL|2026-12-18|put|150000', { lastTradePrice: null, lastTradeTime: '2026-11-17T15:47:12' }],
        ]);
        cacheGetChain.mockResolvedValue(attempt(chain));
        const result = await getDemoOptionChain('AAPL');
        if (!result.ok) throw new Error('expected ok');
        expect(result.expiries[0].strikes[0]).toEqual({ strike: 150, call: null, put: null });
    });
});
