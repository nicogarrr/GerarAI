/**
 * Suite Vitest de lib/market/cboe-options.ts: espejo de
 * scripts/cboe-options.test.ts (node --test, corre en los guards) para que la
 * cobertura del fichero cuente en `vitest run --coverage` (los node-tests no
 * se miden ahí). Mantener ambas suites en sincronía: un comportamiento nuevo
 * se testea en las dos.
 *
 * Además cubre lo que la versión node no alcanza: el fetch real de
 * fetchCboeChain (fetch stubbeado: OK, HTTP no-OK con/sin Retry-After, error
 * de red), los desalojos LRU de la caché (entradas y marcas de fallo) y los
 * valores por defecto de las opciones.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
    cboeContractKey,
    createCboeChainCache,
    fetchCboeChain,
    parseOccSymbol,
    sanitizeCboeChain,
    type CboeChainAttempt,
} from '@/lib/market/cboe-options';

afterEach(() => {
    vi.unstubAllGlobals();
});

describe('parseOccSymbol', () => {
    it('OCC estándar y rechazos', () => {
        expect(parseOccSymbol('ASTS261120C00045000')).toEqual({ underlying: 'ASTS', expiry: '2026-11-20', callPut: 'call', strike: 45 });
        expect(parseOccSymbol('A261218P00050000')).toEqual({ underlying: 'A', expiry: '2026-12-18', callPut: 'put', strike: 50 });
        expect(parseOccSymbol('asts261120c00045500')).toEqual({ underlying: 'ASTS', expiry: '2026-11-20', callPut: 'call', strike: 45.5 });
        // Raíz ajustada (dígito tras letras), mes/día imposibles, formato corto: null.
        expect(parseOccSymbol('ASTS1261120C00045000')).toBeNull();
        expect(parseOccSymbol('ASTS261320C00045000')).toBeNull();
        expect(parseOccSymbol('ASTS261131C00045000')).toBeNull();
        expect(parseOccSymbol('ASTS')).toBeNull();
        expect(parseOccSymbol('ASTS261120C0004500')).toBeNull();
        expect(parseOccSymbol(null)).toBeNull();
        expect(parseOccSymbol(42)).toBeNull();
    });

    it('mes 0, día 0, día 32 y 30 de febrero: fechas que no existen', () => {
        expect(parseOccSymbol('ASTS260020C00045000')).toBeNull();
        expect(parseOccSymbol('ASTS261100C00045000')).toBeNull();
        expect(parseOccSymbol('ASTS261132C00045000')).toBeNull();
        expect(parseOccSymbol('ASTS260230C00045000')).toBeNull();
    });
});

describe('cboeContractKey', () => {
    it('es estable y agnóstica a mayúsculas y decimales de strike', () => {
        expect(cboeContractKey('asts', '2026-11-20', 'call', 45)).toBe(cboeContractKey('ASTS', '2026-11-20', 'call', 45.0));
        expect(cboeContractKey('ASTS', '2026-11-20', 'call', 45)).not.toBe(cboeContractKey('ASTS', '2026-11-20', 'put', 45));
    });

    it('el strike se REDONDEA al milésimo OCC (un suelo rompería strikes de 3 decimales)', () => {
        // 45.29 * 1000 = 45289.99999999999 en coma flotante: con Math.floor la
        // clave sería 45289 y el contrato real 45290 saldría N/D. Round es
        // CORRECTO: el strike OCC lleva exactamente 3 decimales.
        const parsed = parseOccSymbol('ASTS261120C00045290');
        expect(parsed).not.toBeNull();
        expect(cboeContractKey('ASTS', '2026-11-20', 'call', 45.29)).toBe(cboeContractKey(parsed!.underlying, parsed!.expiry, parsed!.callPut, parsed!.strike));
        expect(cboeContractKey('ASTS', '2026-11-20', 'call', 45.29)).toMatch(/\|45290$/);
        // Un strike por ENCIMA de la precisión OCC se aproxima al milésimo más
        // cercano (elección registrada: redondeo, no suelo ni techo).
        expect(cboeContractKey('ASTS', '2026-11-20', 'call', 45.0005)).toMatch(/\|45001$/);
        expect(cboeContractKey('ASTS', '2026-11-20', 'call', 45.0004)).toMatch(/\|45000$/);
    });
});

const cboePayload = {
    data: {
        symbol: 'ASTS',
        options: [
            { option: 'ASTS261120C00045000', last_trade_price: 0.01, last_trade_time: '2026-11-17T15:47:43', bid: 0, ask: 0.01 },
            { option: 'ASTS261218C00050000', last_trade_price: 2.3, last_trade_time: '2026-11-18T14:05:00' },
            // Sin operación registrada: precio y hora a null -> N/D honesto, nunca bid/ask inventado.
            { option: 'ASTS261218C00100000', last_trade_price: null, last_trade_time: null, bid: 0.05, ask: 0.1 },
            // Filas corruptas: se descartan, no envenenan la cadena.
            { option: 'ASTS1X', last_trade_price: 5 },
            { option: 'ASTS261218C00060000', last_trade_price: 'abc', last_trade_time: 'ayer' },
            { option: 'ASTS261218C00070000', last_trade_price: -4, last_trade_time: '2026-11-18T10:00:00' },
        ],
    },
};

describe('sanitizeCboeChain', () => {
    it('mapa por contrato con saneado defensivo', () => {
        const chain = sanitizeCboeChain(cboePayload);
        expect(chain).not.toBeNull();
        expect(chain!.get(cboeContractKey('ASTS', '2026-11-20', 'call', 45))).toEqual({ lastTradePrice: 0.01, lastTradeTime: '2026-11-17T15:47:43' });
        expect(chain!.get(cboeContractKey('ASTS', '2026-12-18', 'call', 50))).toEqual({ lastTradePrice: 2.3, lastTradeTime: '2026-11-18T14:05:00' });
        expect(chain!.get(cboeContractKey('ASTS', '2026-12-18', 'call', 100))).toEqual({ lastTradePrice: null, lastTradeTime: null });
        // 'abc' y -4 no son precio: quedan null (el valuador los deja N/D), nunca NaN ni negativos.
        expect(chain!.get(cboeContractKey('ASTS', '2026-12-18', 'call', 60))).toEqual({ lastTradePrice: null, lastTradeTime: null });
        expect(chain!.get(cboeContractKey('ASTS', '2026-12-18', 'call', 70))?.lastTradePrice).toBeNull();
        expect(sanitizeCboeChain({})).toBeNull();
        expect(sanitizeCboeChain(null)).toBeNull();
        expect(sanitizeCboeChain({ data: { options: 'no-array' } })).toBeNull();
    });

    it('precio vacío o solo espacios NO es 0; hora imposible se descarta', () => {
        const chain = sanitizeCboeChain({
            data: {
                options: [
                    // Auditor 18-nov-2026: Number('') y Number('   ') son 0; sin el
                    // saneado la fila saldría VALORADA a 0 con PyG -100 % inventada.
                    { option: 'ASTS261120C00045000', last_trade_price: '', last_trade_time: '2026-11-17T15:47:43' },
                    { option: 'ASTS261120C00046000', last_trade_price: '   ', last_trade_time: '2026-11-17T15:47:43' },
                    // Horas que pasan el regex pero no existen: se descartan (null),
                    // nunca llegan al formateo de la etiqueta.
                    { option: 'ASTS261120C00047000', last_trade_price: 1.2, last_trade_time: '2026-99-99T99:99:99' },
                    { option: 'ASTS261120C00048000', last_trade_price: 1.2, last_trade_time: '2026-11-18T25:00:00' },
                    { option: 'ASTS261120C00049000', last_trade_price: 1.2, last_trade_time: '2026-02-30T10:00:00' },
                ],
            },
        });
        expect(chain).not.toBeNull();
        expect(chain!.get(cboeContractKey('ASTS', '2026-11-20', 'call', 45))?.lastTradePrice).toBeNull();
        expect(chain!.get(cboeContractKey('ASTS', '2026-11-20', 'call', 46))?.lastTradePrice).toBeNull();
        expect(chain!.get(cboeContractKey('ASTS', '2026-11-20', 'call', 47))?.lastTradeTime).toBeNull();
        expect(chain!.get(cboeContractKey('ASTS', '2026-11-20', 'call', 48))?.lastTradeTime).toBeNull();
        expect(chain!.get(cboeContractKey('ASTS', '2026-11-20', 'call', 49))?.lastTradeTime).toBeNull();
    });

    it('bordes del saneado: minuto/segundo >59, hora sin segundos, precio tope y tipos raros', () => {
        const chain = sanitizeCboeChain({
            data: {
                options: [
                    { option: 'ASTS261120C00041000', last_trade_price: 1, last_trade_time: '2026-11-18T10:61:00' },
                    { option: 'ASTS261120C00042000', last_trade_price: 1, last_trade_time: '2026-11-18T10:00:61' },
                    // Sin segundos: forma admitida (el proveedor a veces los omite).
                    { option: 'ASTS261120C00043000', last_trade_price: 1, last_trade_time: '2026-11-18T10:00' },
                    // Por encima del tope de precio: no es una operación.
                    { option: 'ASTS261120C00044000', last_trade_price: 2_000_000, last_trade_time: '2026-11-18T10:00:00' },
                    // Cadena numérica: se acepta (el proveedor a veces la manda así).
                    { option: 'ASTS261120C00045500', last_trade_price: '2.5', last_trade_time: '2026-11-18T10:00:00' },
                    // Tipo sin sentido (objeto): null.
                    { option: 'ASTS261120C00046000', last_trade_price: { p: 1 }, last_trade_time: '2026-11-18T10:00:00' },
                ],
            },
        });
        expect(chain).not.toBeNull();
        expect(chain!.get(cboeContractKey('ASTS', '2026-11-20', 'call', 41))?.lastTradeTime).toBeNull();
        expect(chain!.get(cboeContractKey('ASTS', '2026-11-20', 'call', 42))?.lastTradeTime).toBeNull();
        expect(chain!.get(cboeContractKey('ASTS', '2026-11-20', 'call', 43))?.lastTradeTime).toBe('2026-11-18T10:00');
        expect(chain!.get(cboeContractKey('ASTS', '2026-11-20', 'call', 44))?.lastTradePrice).toBeNull();
        expect(chain!.get(cboeContractKey('ASTS', '2026-11-20', 'call', 45.5))?.lastTradePrice).toBe(2.5);
        expect(chain!.get(cboeContractKey('ASTS', '2026-11-20', 'call', 46))?.lastTradePrice).toBeNull();
    });
});

const okAttempt = (payload: unknown): CboeChainAttempt => {
    const chain = sanitizeCboeChain(payload);
    return { chain, fetchFailed: !chain, retryAfterSeconds: null };
};

describe('fetchCboeChain (fetch stubbeado)', () => {
    const stubFetch = (impl: (...args: Parameters<typeof fetch>) => Promise<unknown>) => {
        const fetchMock = vi.fn(impl);
        vi.stubGlobal('fetch', fetchMock);
        return fetchMock;
    };

    it('descarga la URL pública de delayed quotes con UA de navegador y sanea', async () => {
        const fetchMock = stubFetch(async () => ({ ok: true, json: async () => cboePayload }) as Response);
        const r = await fetchCboeChain(' asts ');
        expect(r.fetchFailed).toBe(false);
        expect(r.chain?.get(cboeContractKey('ASTS', '2026-12-18', 'call', 50))?.lastTradePrice).toBe(2.3);
        const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
        expect(url).toBe('https://cdn.cboe.com/api/global/delayed_quotes/options/ASTS.json');
        expect((init.headers as Record<string, string>)['user-agent']).toContain('Mozilla/5.0');
        expect(init.cache).toBe('no-store');
    });

    it('respuesta OK con payload irreconocible = fallo de la fuente', async () => {
        stubFetch(async () => ({ ok: true, json: async () => ({ data: { options: 'no-array' } }) }) as unknown as Response);
        const r = await fetchCboeChain('ASTS');
        expect(r).toEqual({ chain: null, fetchFailed: true, retryAfterSeconds: null });
    });

    it('HTTP no-OK: Retry-After válido se propaga; ausente, no numérico o <= 0 queda null', async () => {
        const headersWith = (v: string | null) => ({ get: (k: string) => (k === 'retry-after' ? v : null) });
        stubFetch(async () => ({ ok: false, headers: headersWith('120') }) as unknown as Response);
        expect((await fetchCboeChain('ASTS')).retryAfterSeconds).toBe(120);
        stubFetch(async () => ({ ok: false, headers: headersWith('abc') }) as unknown as Response);
        expect((await fetchCboeChain('ASTS')).retryAfterSeconds).toBeNull();
        stubFetch(async () => ({ ok: false, headers: headersWith(null) }) as unknown as Response);
        expect((await fetchCboeChain('ASTS')).retryAfterSeconds).toBeNull();
        stubFetch(async () => ({ ok: false, headers: headersWith('0') }) as unknown as Response);
        expect((await fetchCboeChain('ASTS')).retryAfterSeconds).toBeNull();
    });

    it('error de red = fallo transitorio, nunca una excepción al llamador', async () => {
        stubFetch(async () => {
            throw new TypeError('fetch failed');
        });
        const r = await fetchCboeChain('ASTS');
        expect(r).toEqual({ chain: null, fetchFailed: true, retryAfterSeconds: null });
    });

    it('valida la forma del subyacente antes de salir a red', async () => {
        const fetchMock = stubFetch(async () => ({ ok: true, json: async () => cboePayload }) as Response);
        const r = await fetchCboeChain('no es un simbolo valido!');
        expect(r).toEqual({ chain: null, fetchFailed: true, retryAfterSeconds: null });
        expect(fetchMock).not.toHaveBeenCalled();
    });
});

describe('createCboeChainCache', () => {
    it('dedupe concurrente, TTL y fetchedAt real', async () => {
        let clock = 1_000_000;
        const cache = createCboeChainCache({ now: () => clock, ttlMs: 60_000 });
        let fetches = 0;
        const fetcher = async () => {
            fetches += 1;
            await new Promise((r) => setTimeout(r, 5));
            return okAttempt(cboePayload);
        };
        const [a, b, c] = await Promise.all([cache.getChain('ASTS', fetcher), cache.getChain('asts ', fetcher), cache.getChain('ASTS', fetcher)]);
        expect(fetches).toBe(1);
        expect(a.chain?.size).toBe(b.chain?.size);
        expect(c.fetchedAt).toBe(a.fetchedAt);
        clock += 30_000;
        await cache.getChain('ASTS', fetcher);
        expect(fetches).toBe(1);
        clock += 31_000;
        await cache.getChain('ASTS', fetcher);
        expect(fetches).toBe(2);
    });

    it('fallo con Retry-After frena el reintento; vencida la ventana reintenta', async () => {
        let clock = 0;
        const cache = createCboeChainCache({ now: () => clock });
        let fetches = 0;
        const failing = async (): Promise<CboeChainAttempt> => {
            fetches += 1;
            return { chain: null, fetchFailed: true, retryAfterSeconds: 120 };
        };
        const first = await cache.getChain('ASTS', failing);
        expect(first.fetchFailed).toBe(true);
        clock += 30_000;
        const second = await cache.getChain('ASTS', failing);
        expect(fetches).toBe(1);
        expect(second.fetchFailed).toBe(true);
        expect(second.retryAfterSeconds ?? 0).toBeGreaterThan(0);
        clock += 91_000;
        await cache.getChain('ASTS', failing);
        expect(fetches).toBe(2);
    });

    it('borde EXACTO del TTL (en ttlMs se sirve, en ttlMs+1 se revalida)', async () => {
        let clock = 1_000_000;
        const cache = createCboeChainCache({ now: () => clock, ttlMs: 60_000 });
        let fetches = 0;
        const fetcher = async (): Promise<CboeChainAttempt> => {
            fetches += 1;
            return okAttempt(cboePayload);
        };
        const first = await cache.getChain('ASTS', fetcher);
        const fetchedAt = first.fetchedAt as number;
        expect(fetches).toBe(1);
        clock = fetchedAt + 60_000;
        await cache.getChain('ASTS', fetcher);
        expect(fetches).toBe(1);
        clock = fetchedAt + 60_001;
        await cache.getChain('ASTS', fetcher);
        expect(fetches).toBe(2);
    });

    it('el Retry-After del proveedor se respeta pero ACOTADO a 300 s', async () => {
        let clock = 0;
        const cache = createCboeChainCache({ now: () => clock });
        let fetches = 0;
        const failing = async (): Promise<CboeChainAttempt> => {
            fetches += 1;
            return { chain: null, fetchFailed: true, retryAfterSeconds: 999 };
        };
        await cache.getChain('ASTS', failing);
        expect(fetches).toBe(1);
        clock += 299_000;
        const blocked = await cache.getChain('ASTS', failing);
        expect(fetches).toBe(1);
        expect(blocked.retryAfterSeconds ?? Infinity).toBeLessThanOrEqual(300);
        clock += 2_000;
        await cache.getChain('ASTS', failing);
        expect(fetches).toBe(2);
    });

    it('saturación de concurrencia = degradado inmediato sin fetch ni bloqueo', async () => {
        const cache = createCboeChainCache({ maxInflight: 2 });
        let fetches = 0;
        const slow = async (): Promise<CboeChainAttempt> => {
            fetches += 1;
            await new Promise((r) => setTimeout(r, 20));
            return okAttempt(cboePayload);
        };
        const p1 = cache.getChain('AAA', slow);
        const p2 = cache.getChain('BBB', slow);
        const third = await cache.getChain('CCC', slow);
        expect(third.saturated).toBe(true);
        expect(third.chain).toBeNull();
        expect(fetches).toBe(2);
        await Promise.all([p1, p2]);
    });

    it('timeout del fetch cuenta como fallo y no envenena con dato tardío', async () => {
        const cache = createCboeChainCache({ fetchTimeoutMs: 10, failureBackoffBaseMs: 1, failureBackoffCapMs: 1 });
        const zombie = async (): Promise<CboeChainAttempt> => {
            await new Promise((r) => setTimeout(r, 100));
            return okAttempt(cboePayload);
        };
        const r = await cache.getChain('ASTS', zombie);
        expect(r.chain).toBeNull();
        expect(r.fetchFailed).toBe(true);
    });

    it('un fetcher que rechaza cuenta como fallo con backoff propio', async () => {
        let clock = 0;
        const cache = createCboeChainCache({ now: () => clock, failureBackoffBaseMs: 10_000, failureBackoffCapMs: 10_000 });
        let fetches = 0;
        const boom = async (): Promise<CboeChainAttempt> => {
            fetches += 1;
            throw new Error('red caída');
        };
        const first = await cache.getChain('ASTS', boom);
        expect(first).toMatchObject({ chain: null, fetchFailed: true, retryAfterSeconds: null });
        clock += 5_000;
        await cache.getChain('ASTS', boom);
        expect(fetches).toBe(1); // dentro del backoff propio no se reintenta
    });

    it('intento sin cadena y sin fetchFailed NO marca fallo: el siguiente lo reintenta al instante', async () => {
        const clock = 0;
        const cache = createCboeChainCache({ now: () => clock });
        let fetches = 0;
        const empty = async (): Promise<CboeChainAttempt> => {
            fetches += 1;
            return { chain: null, fetchFailed: false, retryAfterSeconds: null };
        };
        const r = await cache.getChain('ASTS', empty);
        expect(r).toMatchObject({ chain: null, fetchFailed: false });
        await cache.getChain('ASTS', empty);
        expect(fetches).toBe(2);
    });

    it('al llenarse la caché expulsa la entrada MÁS VIEJA (LRU)', async () => {
        let clock = 0;
        const cache = createCboeChainCache({ now: () => clock, maxEntries: 2 });
        let fetches = 0;
        const fetcher = async (): Promise<CboeChainAttempt> => {
            fetches += 1;
            return okAttempt(cboePayload);
        };
        await cache.getChain('AAA', fetcher);
        clock += 1_000;
        await cache.getChain('BBB', fetcher);
        clock += 1_000;
        await cache.getChain('CCC', fetcher); // expulsa AAA (la más vieja)
        expect(fetches).toBe(3);
        await cache.getChain('BBB', fetcher); // BBB sigue: sin fetch
        expect(fetches).toBe(3);
        await cache.getChain('AAA', fetcher); // AAA fue expulsada: refetch (y expulsa BBB)
        expect(fetches).toBe(4);
    });

    it('al llenarse el registro de fallos expulsa la marca que expira antes', async () => {
        let clock = 0;
        const cache = createCboeChainCache({ now: () => clock, maxFailureMarks: 2 });
        const fetches: Record<string, number> = {};
        const failing = (name: string, retryAfterSeconds: number) => async (): Promise<CboeChainAttempt> => {
            fetches[name] = (fetches[name] ?? 0) + 1;
            return { chain: null, fetchFailed: true, retryAfterSeconds };
        };
        await cache.getChain('AAA', failing('AAA', 10)); // marca AAA: expira en 10 s
        await cache.getChain('BBB', failing('BBB', 20)); // marca BBB: expira en 20 s
        await cache.getChain('CCC', failing('CCC', 30)); // sin plaza: expulsa AAA (expira antes)
        clock += 1_000;
        // AAA ya no tiene marca (fue la expulsada): reintenta al instante y,
        // con un fetcher que ahora funciona, no deja marca nueva.
        const okNow = async (): Promise<CboeChainAttempt> => {
            fetches['AAA'] = (fetches['AAA'] ?? 0) + 1;
            return okAttempt(cboePayload);
        };
        await cache.getChain('AAA', okNow);
        expect(fetches['AAA']).toBe(2);
        await cache.getChain('BBB', failing('BBB', 20)); // BBB tiene marca viva: no reintenta
        expect(fetches['BBB']).toBe(1);
    });

    it('opciones inválidas caen en los valores por defecto documentados', async () => {
        let clock = 0;
        const cache = createCboeChainCache({
            now: () => clock,
            ttlMs: Number.NaN,
            maxEntries: 0,
            maxInflight: -3,
            fetchTimeoutMs: 0,
            maxFailureMarks: 1.5,
            maxRetryAfterSeconds: -1,
            failureBackoffBaseMs: Number.NaN,
            failureBackoffCapMs: 0,
        });
        let fetches = 0;
        const fetcher = async (): Promise<CboeChainAttempt> => {
            fetches += 1;
            return okAttempt(cboePayload);
        };
        await cache.getChain('ASTS', fetcher);
        clock += 30_000; // TTL por defecto 60 s: sigue viva
        await cache.getChain('ASTS', fetcher);
        expect(fetches).toBe(1);
        clock += 31_000; // 61 s: revalida
        await cache.getChain('ASTS', fetcher);
        expect(fetches).toBe(2);
    });
});
