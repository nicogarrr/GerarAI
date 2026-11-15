// @vitest-environment node
import { describe, expect, it } from 'vitest';

import {
    buildVerifyRow,
    formatVerifyRow,
    summarizeVerifyRows,
    verificationPassed,
    type VerifyRow,
} from '@/lib/market/live-markets-verify';
import type { LiveQuoteSpec } from '@/lib/market/live-quotes';

const SPEC: LiveQuoteSpec = { symbol: 'ES=F', name: 'Futuro S&P 500 (E-mini)', kind: 'futuro', unit: 'index', decimals: 2 };
const NY = 'America/New_York';
// Barras jueves/viernes y cotización del viernes 21:00 UTC (mismo día de mercado).
const D1 = Date.UTC(2026, 10, 12, 21, 0) / 1000;
const D2 = Date.UTC(2026, 10, 13, 21, 0) / 1000;
const NOW_MS = (D2 + 3600) * 1000;

interface ChartPayload {
    chart: {
        result: {
            meta: Record<string, unknown>;
            timestamp?: (number | null)[];
            indicators?: { quote: { close?: (number | null)[] }[] };
        }[];
        error: unknown;
    };
}

const payloadOk: ChartPayload = {
    chart: {
        result: [{
            meta: {
                regularMarketPrice: 7583,
                regularMarketTime: D2,
                currency: 'USD',
                exchangeName: 'CME',
                instrumentType: 'FUTURE',
                exchangeTimezoneName: NY,
            },
            timestamp: [D1, D2],
            indicators: { quote: [{ close: [7544.25, 7583] }] },
        }],
        error: null,
    },
};

describe('buildVerifyRow', () => {
    it('fila OK: precio, antigüedad medida, identidad del proveedor y cambio con referencia', () => {
        const row = buildVerifyRow(SPEC, { httpStatus: 200, payload: payloadOk }, NOW_MS);
        expect(row.status).toBe('ok');
        expect(row.price).toBe(7583);
        expect(row.ageSeconds).toBe(3600);
        expect(row.exchangeName).toBe('CME');
        expect(row.instrumentType).toBe('FUTURE');
        expect(row.currency).toBe('USD');
        expect(row.bars).toBe(2);
        expect(row.changeComputable).toBe(true);
        expect(row.symbol).toBe('ES=F');
        expect(row.kind).toBe('futuro');
    });

    it('una sola barra el día de la cotización: precio OK pero cambio sin referencia (N/D)', () => {
        const payload = structuredClone(payloadOk);
        payload.chart.result[0]!.timestamp = [D2];
        payload.chart.result[0]!.indicators!.quote[0]!.close = [7583];
        const row = buildVerifyRow(SPEC, { httpStatus: 200, payload }, NOW_MS);
        expect(row.status).toBe('ok');
        expect(row.bars).toBe(1);
        expect(row.changeComputable).toBe(false);
    });

    it('sin precio utilizable: sin_precio (la UI pintaría N/D)', () => {
        const payload = { chart: { result: [{ meta: { regularMarketPrice: null } }], error: null } };
        const row = buildVerifyRow(SPEC, { httpStatus: 200, payload }, NOW_MS);
        expect(row.status).toBe('sin_precio');
        expect(row.price).toBeNull();
        expect(row.ageSeconds).toBeNull();
    });

    it('fallo de red/timeout (httpStatus null) y HTTP no-2xx: error_http', () => {
        expect(buildVerifyRow(SPEC, { httpStatus: null, payload: null }, NOW_MS).status).toBe('error_http');
        expect(buildVerifyRow(SPEC, { httpStatus: 429, payload: null }, NOW_MS).status).toBe('error_http');
        expect(buildVerifyRow(SPEC, { httpStatus: 500, payload: payloadOk }, NOW_MS).status).toBe('error_http');
    });

    it('payload sin forma chart.result[0] o con chart.error: payload_roto', () => {
        expect(buildVerifyRow(SPEC, { httpStatus: 200, payload: null }, NOW_MS).status).toBe('payload_roto');
        expect(buildVerifyRow(SPEC, { httpStatus: 200, payload: 'texto' }, NOW_MS).status).toBe('payload_roto');
        expect(buildVerifyRow(SPEC, { httpStatus: 200, payload: { chart: { result: [], error: null } } }, NOW_MS).status).toBe('payload_roto');
        expect(buildVerifyRow(SPEC, { httpStatus: 200, payload: { chart: { result: null, error: { code: 'Not Found' } } } }, NOW_MS).status).toBe('payload_roto');
    });

    it('barras con cierre null/0 no cuentan como referencia válida', () => {
        const payload = structuredClone(payloadOk);
        payload.chart.result[0]!.indicators!.quote[0]!.close = [null, 7583];
        const row = buildVerifyRow(SPEC, { httpStatus: 200, payload }, NOW_MS);
        expect(row.bars).toBe(1);
        expect(row.changeComputable).toBe(false);
    });
});

describe('summarizeVerifyRows / verificationPassed', () => {
    const okRow = buildVerifyRow(SPEC, { httpStatus: 200, payload: payloadOk }, NOW_MS);
    const okSinRef: VerifyRow = { ...okRow, changeComputable: false };
    const sinPrecio = buildVerifyRow(SPEC, { httpStatus: 200, payload: { chart: { result: [{ meta: {} }], error: null } } }, NOW_MS);
    const errorHttp = buildVerifyRow(SPEC, { httpStatus: null, payload: null }, NOW_MS);
    const roto = buildVerifyRow(SPEC, { httpStatus: 200, payload: 42 }, NOW_MS);

    it('cuenta por estado y conserva la mayor antigüedad medida', () => {
        const summary = summarizeVerifyRows([okRow, okSinRef, sinPrecio, errorHttp, roto]);
        expect(summary).toEqual({
            total: 5,
            ok: 2,
            sinPrecio: 1,
            errorHttp: 1,
            payloadRoto: 1,
            sinReferencia: 1,
            maxAgeSeconds: 3600,
        });
    });

    it('sin filas OK con hora: antigüedad máxima null', () => {
        expect(summarizeVerifyRows([errorHttp]).maxAgeSeconds).toBeNull();
    });

    it('el veredicto exige TODOS los símbolos del catálogo con precio utilizable', () => {
        expect(verificationPassed([okRow, okSinRef])).toBe(true);
        expect(verificationPassed([okRow, sinPrecio])).toBe(false);
        expect(verificationPassed([errorHttp])).toBe(false);
        expect(verificationPassed([])).toBe(true);
    });
});

describe('formatVerifyRow', () => {
    it('fila OK: símbolo, precio, antigüedad legible, identidad y barras', () => {
        const row = buildVerifyRow(SPEC, { httpStatus: 200, payload: payloadOk }, NOW_MS);
        const line = formatVerifyRow(row);
        expect(line).toContain('ES=F');
        expect(line).toContain('OK');
        expect(line).toContain('price=7583');
        expect(line).toContain('age=hace 1 h');
        expect(line).toContain('CME/FUTURE');
        expect(line).toContain('bars=2');
        expect(line).not.toContain('change=N/D');
    });

    it('marca el cambio N/D cuando no hay referencia y la antigüedad N/D sin hora', () => {
        const row = buildVerifyRow(SPEC, { httpStatus: 200, payload: payloadOk }, NOW_MS);
        const line = formatVerifyRow({ ...row, changeComputable: false, ageSeconds: null });
        expect(line).toContain('change=N/D');
        expect(line).toContain('age=N/D');
    });

    it('fila fallida: solo símbolo y estado, sin columnas inventadas', () => {
        const line = formatVerifyRow(buildVerifyRow(SPEC, { httpStatus: null, payload: null }, NOW_MS));
        expect(line).toContain('HTTP_ERROR');
        expect(line).not.toContain('price=');
        expect(line).not.toContain('bars=');
    });

    it('locale en: antigüedad en inglés', () => {
        const row = buildVerifyRow(SPEC, { httpStatus: 200, payload: payloadOk }, NOW_MS);
        expect(formatVerifyRow(row, 'en')).toContain('age=1 h ago');
    });
});
