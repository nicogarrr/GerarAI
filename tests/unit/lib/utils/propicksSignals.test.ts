// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ insider: vi.fn() }));
vi.mock('@/lib/actions/insider.actions', () => ({ getInsiderSignals: mocks.insider }));

import { getSignalOverlays } from '@/lib/utils/propicksSignals';

const CUTOFF = '2026-10-15T12:00:00Z';

// fetch por patrón de URL; cada test define lo que responde cada fuente.
function stubFetch(handler: (url: string) => Response | null) {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        const res = handler(url);
        if (res) return res;
        return new Response('no', { status: 404 });
    }));
}
const json = (data: unknown) => new Response(JSON.stringify(data), { status: 200 });
const text = (t: string) => new Response(t, { status: 200 });

beforeEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    mocks.insider.mockReset();
    mocks.insider.mockResolvedValue({ signals: [] });
    vi.stubEnv('FINNHUB_API_KEY', '');
    vi.stubEnv('FRED_API_KEY', '');
    stubFetch(() => null); // por defecto todo 404: sin overlays
});

describe('getSignalOverlays - garantías globales', () => {
    it('entrada inválida devuelve [] sin lanzar', async () => {
        expect(await getSignalOverlays('', CUTOFF)).toEqual([]);
        expect(await getSignalOverlays('AAPL', 'no-es-fecha')).toEqual([]);
    });
    it('si TODAS las fuentes fallan, devuelve [] (nunca lanza)', async () => {
        vi.stubEnv('FINNHUB_API_KEY', 'k');
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('red caída'); }));
        mocks.insider.mockRejectedValue(new Error('backend caído'));
        expect(await getSignalOverlays('AAPL', CUTOFF)).toEqual([]);
    });
});

describe('overlay de revisiones (Finnhub earnings)', () => {
    it('sin API key no hay overlay (no se inventa)', async () => {
        expect(await getSignalOverlays('AAPL', CUTOFF)).toEqual([]);
    });
    it('media de sorpresas de los últimos 4 trimestres <= asOf, impacto = media/2', async () => {
        vi.stubEnv('FINNHUB_API_KEY', 'k');
        stubFetch((url) => url.includes('finnhub.io') ? json([
            { actual: 1.1, estimate: 1.0, period: '2026-09-30' },  // +10 %
            { actual: 1.0, estimate: 1.0, period: '2026-06-30' },  // 0 %
            { actual: 2.0, estimate: 1.0, period: '2027-03-31' },  // futuro: se descarta
            { actual: 1.0, estimate: 0, period: '2026-03-31' },    // estimate 0: se descarta
        ]) : null);
        const out = await getSignalOverlays('AAPL', CUTOFF);
        const rev = out.find((o) => o.factor === 'revisiones');
        expect(rev).toBeDefined();
        expect(rev!.impact).toBe(2.5); // media +5 % → 5/2
        expect(rev!.value).toBe(5);
        expect(rev!.detail).toContain('(valor 5)'); // R5: valor crudo literal
        expect(rev!.detail).toContain('2 trimestres');
        expect(rev!.detail).toContain('hasta 2026-09-30');
        expect(rev!.asOf).toBe('2026-10-15');
    });
    it('sorpresa media 0 no produce overlay (impacto nulo)', async () => {
        vi.stubEnv('FINNHUB_API_KEY', 'k');
        stubFetch((url) => url.includes('finnhub.io') ? json([
            { actual: 1, estimate: 1, period: '2026-09-30' },
        ]) : null);
        expect((await getSignalOverlays('AAPL', '2026-10-16T12:00:00Z')).find((o) => o.factor === 'revisiones')).toBeUndefined();
    });
});

describe('overlay insider (server action)', () => {
    it('compras y ventas netas en 90 días; ambiguas y futuras no cuentan', async () => {
        mocks.insider.mockResolvedValue({
            signals: [
                { filing_date: '2026-10-01', transaction_type: 'P-Purchase', shares: 1000 },
                { filed_at: '2026-09-20', transaction_type: 'P-Purchase', shares: 800 },
                { filing_date: '2026-10-05', transaction_type: 'S-Sale', shares: 500 },
                { filing_date: '2026-12-01', transaction_type: 'P-Purchase', shares: 9999 }, // futuro
                { transaction_type: 'P-Purchase', shares: 9999 },                             // sin fecha: no demostrable
                { filing_date: '2026-10-03', transaction_type: 'A-Grant', shares: 9999 },     // dirección ambigua
                { filing_date: '2026-01-01', transaction_type: 'P-Purchase', shares: 9999 },  // fuera de la ventana 90d
            ],
        });
        const out = await getSignalOverlays('AAPL', CUTOFF);
        const ins = out.find((o) => o.factor === 'insider');
        expect(ins).toBeDefined();
        expect(ins!.impact).toBe(3.3); // (2 compras - 1 venta) / 3 * 10
        expect(ins!.value).toBe(1300); // 1000 + 800 - 500
        expect(ins!.detail).toContain('2 compras frente a 1 venta');
        expect(ins!.detail).toContain('(valor 1300)');
    });
    it('empate compras/ventas no produce overlay', async () => {
        mocks.insider.mockResolvedValue({
            signals: [
                { filing_date: '2026-10-01', transaction_type: 'P-Purchase', shares: 100 },
                { filing_date: '2026-10-02', transaction_type: 'S-Sale', shares: 100 },
            ],
        });
        expect((await getSignalOverlays('AAPL', CUTOFF)).find((o) => o.factor === 'insider')).toBeUndefined();
    });
});

describe('overlay short interest (FINRA)', () => {
    it('parsea el fichero y aplica la heurística por tramos', async () => {
        stubFetch((url) => url.includes('cdn.finra.org')
            ? text('2026-10-15|AAPL|1234567|extra\n2026-10-15|MSFT|50')
            : null);
        const out = await getSignalOverlays('AAPL', CUTOFF);
        const si = out.find((o) => o.factor === 'shortInterest');
        expect(si).toBeDefined();
        expect(si!.impact).toBe(-3); // >= 1M y < 10M
        expect(si!.value).toBe(1234567);
        expect(si!.detail).toContain('1.234.567 acciones a 2026-10-15');
    });
    it('el token de fecha NO se confunde con el número de acciones (bug de ~20M)', async () => {
        stubFetch((url) => url.includes('cdn.finra.org')
            ? text('TSLA|20261015|500')
            : null);
        // SI real 500 < 100.000 → impacto 0 → sin overlay. Con el bug, la
        // fecha (20.261.015) se tomaba como SI y daba -6.
        expect((await getSignalOverlays('TSLA', '2026-10-17T12:00:00Z')).find((o) => o.factor === 'shortInterest')).toBeUndefined();
    });
    it('una liquidación posterior al corte no se usa', async () => {
        stubFetch((url) => url.includes('cdn.finra.org')
            ? text('2026-10-31|XYZW|9000000')
            : null);
        expect((await getSignalOverlays('XYZW', '2026-10-18T12:00:00Z')).find((o) => o.factor === 'shortInterest')).toBeUndefined();
    });
});

describe('overlay de régimen (VIX)', () => {
    it('VIX > 35: pánico (-8); el último cierre <= asOf manda', async () => {
        stubFetch((url) => url.includes('stooq.com')
            ? text('Date,Open,High,Low,Close,Volume\n2026-10-10,1,2,3,40.5,0\n2026-10-21,1,2,3,50,0\n')
            : null);
        const out = await getSignalOverlays('AAPL', '2026-10-20T12:00:00Z');
        const reg = out.find((o) => o.factor === 'regimen');
        expect(reg).toBeDefined();
        expect(reg!.impact).toBe(-8);
        expect(reg!.detail).toContain('VIX en 40,5 el 2026-10-10 (régimen de pánico)');
        expect(reg!.detail).toContain('(valor 40.5)');
    });
    it('VIX en zona neutra (15-25): sin overlay, no se inventa señal', async () => {
        stubFetch((url) => url.includes('stooq.com')
            ? text('Date,Open,High,Low,Close,Volume\n2026-10-10,1,2,3,20,0\n')
            : null);
        expect((await getSignalOverlays('AAPL', '2026-10-21T12:00:00Z')).find((o) => o.factor === 'regimen')).toBeUndefined();
    });
    it('VIX < 15: complacencia (+2)', async () => {
        stubFetch((url) => url.includes('stooq.com')
            ? text('Date,Open,High,Low,Close,Volume\n2026-10-10,1,2,3,12,0\n')
            : null);
        const reg = (await getSignalOverlays('AAPL', '2026-10-22T12:00:00Z')).find((o) => o.factor === 'regimen');
        expect(reg).toMatchObject({ factor: 'regimen', impact: 2 });
    });
    it('con FRED key usa FRED y respeta observation_end <= asOf', async () => {
        vi.stubEnv('FRED_API_KEY', 'k');
        stubFetch((url) => url.includes('stlouisfed.org')
            ? json({ observations: [{ date: '2026-10-14', value: '32' }] })
            : null);
        const reg = (await getSignalOverlays('AAPL', '2026-10-23T12:00:00Z')).find((o) => o.factor === 'regimen');
        expect(reg).toMatchObject({ impact: -5 });
        expect(reg!.detail).toContain('aversión al riesgo alta');
    });
    it('FRED con «.» (festivo) cae a Stooq; si tampoco hay dato, sin overlay', async () => {
        vi.stubEnv('FRED_API_KEY', 'k');
        stubFetch((url) => url.includes('stlouisfed.org')
            ? json({ observations: [{ date: '2026-10-14', value: '.' }] })
            : null);
        expect((await getSignalOverlays('AAPL', '2026-10-24T12:00:00Z')).find((o) => o.factor === 'regimen')).toBeUndefined();
    });
});
