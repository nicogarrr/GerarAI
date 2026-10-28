import { describe, expect, it } from 'vitest';
import {
    TTM_PANEL_METRICS, isoDateEs, ttmBasisLabel, ttmHasData, ttmPanelMetrics, ttmPeriodText, ttmQuartersText,
    type ResearchTtm, type ResearchTtmMetric,
} from '@/lib/research/ttm-display';

const metric = (over: Partial<ResearchTtmMetric>): ResearchTtmMetric => ({
    metric: 'revenue', value: 1, unit: 'USD', basis: 'TTM', label: 'x', provenance: 'OFICIAL', period_end: '2026-06-30', ...over,
});

describe('isoDateEs', () => {
    it('ISO -> dd/mm/aaaa sin desplazar día por zona; basura -> null', () => {
        expect(isoDateEs('2026-06-30')).toBe('30/06/2026');
        expect(isoDateEs('2026-06-30T23:59:59Z')).toBe('30/06/2026');
        expect(isoDateEs('30/06/2026')).toBeNull();
        expect(isoDateEs(null)).toBeNull();
        expect(isoDateEs('')).toBeNull();
    });
});

describe('ttmBasisLabel / ttmPeriodText', () => {
    it('etiquetas y respaldo ante base desconocida', () => {
        expect(ttmBasisLabel('FY')).toBe('FY (último ejercicio)');
        expect(ttmBasisLabel('XX' as never)).toBe('Sin datos');
    });
    it('TTM dice "hasta", FY/Q dicen "cierre"', () => {
        expect(ttmPeriodText({ basis: 'TTM', period_end: '2026-06-30' })).toBe('TTM (últimos 4 trimestres) · hasta 30/06/2026');
        expect(ttmPeriodText({ basis: 'FY', period_end: '2025-12-31' })).toBe('FY (último ejercicio) · cierre 31/12/2025');
        expect(ttmPeriodText({ basis: 'Q', period_end: '2026-03-31' })).toBe('Último trimestre · cierre 31/03/2026');
    });
    it('sin fecha o sin datos: solo la etiqueta', () => {
        expect(ttmPeriodText({ basis: 'TTM', period_end: null })).toBe('TTM (últimos 4 trimestres)');
        expect(ttmPeriodText({ basis: 'SIN_DATOS', period_end: '2026-06-30' })).toBe('Sin datos');
    });
});

describe('ttmQuartersText', () => {
    it('vacío -> null', () => {
        expect(ttmQuartersText(undefined)).toBeNull();
        expect(ttmQuartersText([])).toBeNull();
    });
    it('marca como inferidos el Q4 por FY−9M y el acumulado restado; el reportado va limpio', () => {
        const out = ttmQuartersText([
            { period_end: '2025-12-31', value: 1, reported: false, origin: 'FY-9M' },
            { period_end: '2026-03-31', value: 1, reported: true, origin: 'filing' },
            { period_end: '2026-06-30', value: 1, reported: false, origin: 'ytd' },
        ]);
        expect(out).toBe('31/12/2025 (Q4 = FY − 9 meses, inferido) + 31/03/2026 + 30/06/2026 (acumulado restado, inferido)');
    });
    it('fecha no ISO se deja tal cual', () => {
        expect(ttmQuartersText([{ period_end: 'Q1-26', value: 1, reported: true, origin: 'f' }])).toBe('Q1-26');
    });
});

describe('ttmPanelMetrics / ttmHasData', () => {
    it('null -> vacío y sin datos', () => {
        expect(ttmPanelMetrics(null)).toEqual([]);
        expect(ttmHasData(null)).toBe(false);
    });
    it('respeta el orden del panel e ignora métricas fuera de panel', () => {
        const ttm: ResearchTtm = { ticker: 'X', as_of: null, formula: '', metrics: [
            metric({ metric: 'net_income' }), metric({ metric: 'revenue' }), metric({ metric: 'otra' }),
        ] };
        expect(ttmPanelMetrics(ttm).map(m => m.metric)).toEqual(['revenue', 'net_income']);
        expect(TTM_PANEL_METRICS[0]).toBe('revenue');
    });
    it('hay datos solo si algún valor no nulo con base distinta de SIN_DATOS', () => {
        const mk = (m: ResearchTtmMetric[]): ResearchTtm => ({ ticker: 'X', as_of: null, formula: '', metrics: m });
        expect(ttmHasData(mk([metric({ value: null })]))).toBe(false);
        expect(ttmHasData(mk([metric({ basis: 'SIN_DATOS', value: 5 })]))).toBe(false);
        expect(ttmHasData(mk([metric({ value: 0 })]))).toBe(true);
    });
});
