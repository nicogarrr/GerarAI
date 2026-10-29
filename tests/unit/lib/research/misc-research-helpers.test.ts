import { describe, expect, it, vi } from 'vitest';
import { canonicalRedirectTicker } from '@/lib/research/canonical-ticker';
import { CHAT_INTENTS, chatIntentHref } from '@/lib/research/chat-intents';
import { groupClaimsByVersion } from '@/lib/research/claim-groups';
import { corporateActionsEmptyMessage } from '@/lib/research/corporate-actions-empty';
import { debateErrorMessage } from '@/lib/research/debate-error';
import { ownershipLimitations } from '@/lib/research/ownership-display';
import { groupReviews } from '@/lib/research/review-groups';
import { fetchInBatches } from '@/lib/research/snapshots';
import { thesisCodeLabel } from '@/lib/research/thesis-code-label';
import { thesisEps, thesisMoney } from '@/lib/research/thesis-number-format';
import { looksLikeTicker } from '@/lib/research/ticker-shape';
import { findUnavailableViewFailure, viewRetryHref } from '@/lib/research/view-outage';
import { xirrUnavailableReason } from '@/lib/research/xirr-status';
import { drainRejection } from '@/lib/research/drain-rejection';
import { portfolioMembership } from '@/lib/research/portfolio-membership';

describe('canonicalRedirectTicker', () => {
    it('sin resolución o igual: no redirige', () => {
        expect(canonicalRedirectTicker('AAPL', null)).toBeNull();
        expect(canonicalRedirectTicker('aapl', ' AAPL ')).toBeNull();
    });
    it('BRK-B -> BRK.B, y sufijo de bolsa -> ticker base', () => {
        expect(canonicalRedirectTicker('brk-b', 'BRK.B')).toBe('BRK.B');
        expect(canonicalRedirectTicker('SAN.MC', 'SAN')).toBe('SAN');
    });
    it('no redirige a un ticker distinto (evita mostrar otra empresa)', () => {
        expect(canonicalRedirectTicker('SAN.MC', 'BBVA')).toBeNull();
        expect(canonicalRedirectTicker('ABC-C', 'ABC.C')).toBeNull();
        expect(canonicalRedirectTicker('.X', 'X')).toBeNull();
        expect(canonicalRedirectTicker('AAPL', 'MSFT')).toBeNull();
    });
});

describe('chat intents', () => {
    it('el enlace codifica ticker y pregunta y apunta al ancla del chat', () => {
        const href = chatIntentHref('BRK/B', CHAT_INTENTS[0]);
        expect(href.startsWith('/research/BRK%2FB?view=chat&chat=')).toBe(true);
        expect(href.endsWith('#chat-empresa')).toBe(true);
        expect(decodeURIComponent(href.split('chat=')[1].split('#')[0])).toBe(CHAT_INTENTS[0].question('BRK/B'));
    });
    it('las tres intenciones mencionan el ticker', () => {
        for (const i of CHAT_INTENTS) expect(i.question('XYZ')).toContain('XYZ');
    });
});

describe('groupClaimsByVersion', () => {
    it('agrupa por versión de tesis, con etiquetas honestas para vínculos rotos', () => {
        const out = groupClaimsByVersion(
            [{ thesis_version_id: 2, n: 1 }, { thesis_version_id: null, n: 2 }, { thesis_version_id: 2, n: 3 }, { thesis_version_id: 9, n: 4 }],
            [{ id: 2, version: 5 }],
        );
        expect(out.map((g) => [g.key, g.label, g.claims.length])).toEqual([
            ['thesis-2', 'Tesis v5', 2], ['manual', 'Sin versión de tesis vinculada', 1], ['thesis-9', 'Tesis vinculada (ID 9, versión N/D)', 1],
        ]);
    });
    it('vacío', () => {
        expect(groupClaimsByVersion([], [])).toEqual([]);
    });
});

describe('corporateActionsEmptyMessage', () => {
    it('sin estado, sin importaciones, y con fecha (la más reciente, hora de Madrid)', () => {
        expect(corporateActionsEmptyMessage(null)).toMatch(/sin estado de las fuentes/);
        expect(corporateActionsEmptyMessage({ dividends_last_import: null, splits_last_import: 'basura' })).toMatch(/todavía no se ha importado/);
        expect(corporateActionsEmptyMessage({ dividends_last_import: '2026-10-01T10:00:00Z', splits_last_import: '2026-10-05T23:30:00Z' }))
            .toBe('Sin eventos pendientes. Última importación de datos: 06/10/2026.');
    });
});

describe('debateErrorMessage', () => {
    it('mensajes públicos conocidos pasan tal cual', () => {
        expect(debateErrorMessage(new Error('LLM gratuito agotado, vuelve más tarde'))).toBe('LLM gratuito agotado, vuelve más tarde');
    });
    it('no filtra errores internos (claves, rutas)', () => {
        const msg = debateErrorMessage(new Error('401 invalid api key sk-secret at /srv/app'));
        expect(msg).toBe('No se pudo generar el debate; reinténtalo.');
        expect(msg).not.toContain('sk-secret');
        expect(debateErrorMessage('boom')).toBe('No se pudo generar el debate; reinténtalo.');
    });
    it('timeout/abort, también si vienen envueltos en originalError', () => {
        const inner = new Error('t'); inner.name = 'TimeoutError';
        const wrapped = Object.assign(new Error('x'), { originalError: inner });
        expect(debateErrorMessage(wrapped)).toBe('El debate tardó demasiado; vuelve más tarde');
        const abort = new Error('x'); abort.name = 'AbortError';
        expect(debateErrorMessage(abort)).toMatch(/tardó demasiado/);
    });
});

describe('ownershipLimitations', () => {
    it('vacío -> cadena vacía; SIN_DATOS -> N/D; traduce limitaciones conocidas; une listas', () => {
        expect(ownershipLimitations(null)).toBe('');
        expect(ownershipLimitations([])).toBe('');
        expect(ownershipLimitations('Datos SIN_DATOS')).toBe('Datos N/D');
        expect(ownershipLimitations(['Amendments are separate immutable filings', 'otra'])).toBe('Las enmiendas son declaraciones inmutables independientes. otra');
    });
});

describe('groupReviews', () => {
    it('agrupa por título normalizado, cuenta, conserva la última fecha y ordena por reciente', () => {
        const out = groupReviews([
            { id: 1, title: 'Revisar  tesis', created_at: '2026-10-01' },
            { id: 2, title: 'otra', created_at: '2026-10-05' },
            { id: 3, title: ' revisar tesis ', created_at: '2026-10-03' },
            { id: 4, title: 'REVISAR TESIS', created_at: null },
        ]);
        expect(out).toEqual([
            { title: 'otra', count: 1, latest: '2026-10-05', ids: [2] },
            { title: 'Revisar  tesis', count: 3, latest: '2026-10-03', ids: [1, 3, 4] },
        ]);
    });
    it('sin fechas: no rompe el orden', () => {
        expect(groupReviews([{ id: 1, title: 'a' }, { id: 2, title: 'b' }])).toHaveLength(2);
    });
});

describe('fetchInBatches', () => {
    it('trocea y conserva el orden; un lote que falla da null sin tumbar los demás', async () => {
        const fetchBatch = vi.fn(async (batch: string[]) => { if (batch.includes('c')) throw new Error('x'); return batch.join(''); });
        const out = await fetchInBatches(['a', 'b', 'c', 'd', 'e'], 2, fetchBatch);
        expect(out).toEqual(['ab', null, 'e']);
        expect(fetchBatch).toHaveBeenCalledTimes(3);
    });
    it('sin elementos no llama; tamaño < 1 es error', async () => {
        const f = vi.fn();
        expect(await fetchInBatches([], 5, f)).toEqual([]);
        expect(f).not.toHaveBeenCalled();
        await expect(fetchInBatches(['a'], 0, f)).rejects.toThrow(/batchSize/);
    });
});

describe('thesisCodeLabel', () => {
    it('códigos conocidos en español; texto con formato libre intacto; desconocido intacto', () => {
        expect(thesisCodeLabel('insufficient_data')).toBe('datos insuficientes');
        expect(thesisCodeLabel('Texto libre')).toBe('Texto libre');
        expect(thesisCodeLabel('traceable_wacc')).toBe('WACC trazable');
        expect(thesisCodeLabel('zz_desconocido')).toBe('zz_desconocido');
        expect(thesisCodeLabel('market_cap')).toBe('Capitalización bursátil');
    });
});

describe('thesisMoney / thesisEps', () => {
    it('USD en inglés, otras en es-ES, siempre 2 decimales', () => {
        expect(thesisMoney(1234.5, 'USD')).toBe('1.234,50\u00a0US$');
        expect(thesisMoney(1234.5, 'EUR')).toMatch(/^1\.234,50\s€$/);
    });
    it('BPA: N/D sin dato o no finito (nunca 0.00)', () => {
        for (const v of [null, undefined, NaN, Infinity]) expect(thesisEps(v)).toBe('N/D');
        expect(thesisEps(0)).toBe('0,00');
        expect(thesisEps(-1.234)).toBe('-1,23');
    });
});

describe('looksLikeTicker', () => {
    it.each(['AAPL', 'brk.b', 'BRK-B', '%5EGSPC', '^GSPC', 'EURUSD=X', 'SAN.MC', ' msft '])('acepta %s', (t) => expect(looksLikeTicker(t)).toBe(true));
    it.each(['', 'TOOLONGTICKER', 'A B', '../etc/passwd', '<script>', '%E0%A4%A', 'AAPL;DROP', 'A.B.C', 'ABC.12345'])('rechaza %s', (t) => expect(looksLikeTicker(t)).toBe(false));
});

describe('view-outage', () => {
    it('devuelve el primer fallo de indisponibilidad, ignora otros fallos y éxitos', () => {
        const e1 = new Error('down');
        const settled = [
            { key: 'a', ok: true as const }, { key: 'b', ok: false as const, reason: 'otro', error: new Error('404') },
            { key: 'c', ok: false as const, reason: 'caído', error: e1 }, { key: 'd', ok: false as const, reason: 'caído2', error: e1 },
        ];
        expect(findUnavailableViewFailure(settled, (e) => e === e1)).toEqual({ key: 'c', reason: 'caído' });
        expect(findUnavailableViewFailure(settled, () => false)).toBeNull();
        expect(findUnavailableViewFailure([], () => true)).toBeNull();
    });
    it('reintento conserva la vista activa', () => {
        expect(viewRetryHref('AAPL', 'overview')).toBe('/research/AAPL');
        expect(viewRetryHref('BRK/B', 'holders')).toBe('/research/BRK%2FB?view=holders');
    });
});

describe('xirrUnavailableReason', () => {
    it('motivo concreto por estado y respaldo genérico', () => {
        expect(xirrUnavailableReason('no_xirr_root')).toMatch(/no converge/);
        expect(xirrUnavailableReason('incomplete_missing_fx')).toMatch(/tipos de cambio/);
        expect(xirrUnavailableReason(undefined)).toMatch(/sin flujos suficientes/);
        expect(xirrUnavailableReason({})).toMatch(/sin flujos suficientes/);
    });
});

describe('drainRejection / portfolioMembership', () => {
    it('drainRejection se traga el rechazo y acepta undefined', async () => {
        const rejected = Promise.reject(new Error('x'));
        expect(() => drainRejection(rejected)).not.toThrow();
        expect(() => drainRejection(undefined)).not.toThrow();
        await expect(rejected).rejects.toThrow('x');
    });
    it('membership: ignora posiciones cerradas (cantidad 0) y tickers vacíos; normaliza', () => {
        expect(portfolioMembership([
            { ticker: ' aapl ', quantity: 2 }, { ticker: 'MSFT', quantity: 0 }, { ticker: '  ', quantity: 5 }, { ticker: 'tsla', quantity: -1 },
        ])).toEqual(new Set(['AAPL', 'TSLA']));
    });
});
