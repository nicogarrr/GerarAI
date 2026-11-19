import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
    osaDistance,
    rankSecRows,
    resetSecUniverseCacheForTests,
    searchSecUniverse,
} from '@/lib/market/sec-universe-search';

const SEC_PAYLOAD = {
    fields: ['cik', 'name', 'ticker', 'exchange'],
    data: [
        [2130357, 'Anthropic, PBC', 'ANT', null],
        [789019, 'Microsoft Corp', 'MSFT', 'Nasdaq'],
        [320193, 'Apple Inc.', 'AAPL', 'Nasdaq'],
        [1, 'Zqxwvut Corporation', 'ZQX', 'NYSE'],
    ],
};

const stubSecFetch = (payload: unknown = SEC_PAYLOAD, ok = true) =>
    vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => ({ ok, json: async () => payload }));

describe('osaDistance', () => {
    it('espejo de la política del Cerebro: 1 letra, transposición, corte en limit', () => {
        expect(osaDistance('antrophic', 'anthropic', 2)).toBe(2); // insertar h + transposición r/h
        expect(osaDistance('mcirosoft', 'microsoft', 1)).toBe(1); // transposición de vecinas
        expect(osaDistance('antrhopic', 'antrophic', 2)).toBe(2);
        expect(osaDistance('abcd', 'wxyz', 2)).toBe(3); // corta en limit + 1
        expect(osaDistance('corta', 'muchomaslarga', 2)).toBe(3); // banda de longitud
    });
});

describe('rankSecRows', () => {
    const rows = [
        { ticker: 'ANT', name: 'Anthropic, PBC', exchange: null },
        { ticker: 'ANH', name: 'Anthropic Health', exchange: 'Nasdaq' },
    ];

    it('«Antrophic» (la errata real) encuentra Anthropic', () => {
        expect(rankSecRows('Antrophic', rows).map((r) => r.ticker)).toEqual(['ANH', 'ANT']);
    });

    it('sin candidata clara no inventa nada', () => {
        expect(rankSecRows('zzqqxw', rows)).toEqual([]);
        expect(rankSecRows('ant', rows)).toEqual([]); // < 5 letras: no se adivina
        expect(rankSecRows('anthr0piczz', rows)).toEqual([]); // con dígitos no es nombre
    });
});

describe('searchSecUniverse', () => {
    beforeEach(() => {
        resetSecUniverseCacheForTests();
        vi.useFakeTimers();
        vi.setSystemTime(new Date('2026-11-19T21:00:00Z'));
    });

    afterEach(() => {
        vi.useRealTimers();
        vi.unstubAllGlobals();
    });

    it('mapea la errata al ticker real con bolsa honesta (null -> US, Nasdaq -> NASDAQ)', async () => {
        vi.stubGlobal('fetch', stubSecFetch());
        const result = await searchSecUniverse('Antrophic');
        expect(result).toEqual([
            { symbol: 'ANT', name: 'Anthropic, PBC', exchange: 'US', type: 'Stock', isInWatchlist: false },
        ]);
        const msft = await searchSecUniverse('Mcirosoft');
        expect(msft[0]).toMatchObject({ symbol: 'MSFT', exchange: 'NASDAQ' });
    });

    it('cachea el registro 24 h: dos búsquedas, una sola descarga', async () => {
        const fetchMock = stubSecFetch();
        vi.stubGlobal('fetch', fetchMock);
        await searchSecUniverse('Antrophic');
        await searchSecUniverse('Mcirosoft');
        expect(fetchMock).toHaveBeenCalledTimes(1);
        const init = fetchMock.mock.calls[0][1] as RequestInit;
        expect(String((init.headers as Record<string, string>)['User-Agent'])).toContain('GerarAI');
    });

    it('fallo de la SEC -> vacío sin lanzar, con backoff de 5 min antes de reintentar', async () => {
        const fetchMock = stubSecFetch({}, false);
        vi.stubGlobal('fetch', fetchMock);
        expect(await searchSecUniverse('Antrophic')).toEqual([]);
        await searchSecUniverse('Mcirosoft');
        expect(fetchMock).toHaveBeenCalledTimes(1); // backoff: no martillea sec.gov
        vi.setSystemTime(new Date('2026-11-19T21:06:00Z'));
        await searchSecUniverse('Mcirosoft');
        expect(fetchMock).toHaveBeenCalledTimes(2); // pasado el backoff reintenta
    });

    it('payload raro o sin las columnas esperadas -> vacío, nunca revienta el buscador', async () => {
        vi.stubGlobal('fetch', stubSecFetch({ fields: ['otra'], data: 'no-array' }));
        expect(await searchSecUniverse('Antrophic')).toEqual([]);
        resetSecUniverseCacheForTests();
        vi.stubGlobal('fetch', stubSecFetch(null));
        expect(await searchSecUniverse('Antrophic')).toEqual([]);
    });
});
