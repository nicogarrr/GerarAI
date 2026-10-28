import { describe, expect, it } from 'vitest';
import { sanitizeDebate, sanitizeLlmText } from '@/lib/research/debate-sanitize';

describe('sanitizeLlmText', () => {
    it('no texto -> vacío', () => {
        for (const v of [null, undefined, 5, {}]) expect(sanitizeLlmText(v)).toBe('');
    });
    it('quita caracteres de control, de ancho cero y bidireccionales (ataques de ocultación)', () => {
        expect(sanitizeLlmText('a\u0000b\u200Bc\u202Ed\u2060e')).toBe('abcde');
    });
    it('quita CJK que el modelo cuela en prosa española', () => {
        expect(sanitizeLlmText('Ingresos 增长 suben')).toBe('Ingresos suben');
    });
    it('conserva tildes, ñ, euros y saltos de línea; colapsa espacios y líneas en blanco', () => {
        expect(sanitizeLlmText('Año   2026:\t\t€5\n\n\n\nFin ')).toBe('Año 2026: €5\n\nFin');
    });
    it('acota la longitud', () => {
        expect(sanitizeLlmText('x'.repeat(10000))).toHaveLength(6000);
        expect(sanitizeLlmText('abcdef', 3)).toBe('abc');
    });
});

describe('sanitizeDebate', () => {
    const ok = { ticker: 'AAPL', bull_case: 'alza', bear_case: 'baja', verdict: 'bullish', verdict_rationale: 'porque', llm_calls: 3.9, degraded: true, model: 'm', thesis_version_id: 4, persisted: false };
    it('no objeto o sin ningún texto útil -> null', () => {
        expect(sanitizeDebate(null)).toBeNull();
        expect(sanitizeDebate('x')).toBeNull();
        expect(sanitizeDebate({ bull_case: '\u200B', bear_case: 5 })).toBeNull();
    });
    it('debate válido se normaliza', () => {
        expect(sanitizeDebate(ok)).toEqual({
            ticker: 'AAPL', thesis_version_id: 4, persisted: false, bull_case: 'alza', bear_case: 'baja', verdict: 'bullish',
            verdict_rationale: 'porque', llm_calls: 3, degraded: true, model: 'm',
        });
    });
    it('veredicto inventado -> neutral; degraded solo si es exactamente true', () => {
        expect(sanitizeDebate({ ...ok, verdict: 'to the moon', degraded: 'true' })).toMatchObject({ verdict: 'neutral', degraded: false });
    });
    it('llm_calls negativo, NaN o ausente -> 0', () => {
        expect(sanitizeDebate({ ...ok, llm_calls: -4 })?.llm_calls).toBe(0);
        expect(sanitizeDebate({ ...ok, llm_calls: NaN })?.llm_calls).toBe(0);
        expect(sanitizeDebate({ ...ok, llm_calls: undefined })?.llm_calls).toBe(0);
    });
    it('model vacío tras sanear -> null; campos de tipo erróneo -> undefined', () => {
        const r = sanitizeDebate({ ...ok, model: '\u200B', thesis_version_id: '4', persisted: 'no' });
        expect(r?.model).toBeNull();
        expect(r?.thesis_version_id).toBeUndefined();
        expect(r?.persisted).toBeUndefined();
    });
    it('el ticker se recorta a 20', () => {
        expect(sanitizeDebate({ ...ok, ticker: 'T'.repeat(50) })?.ticker).toHaveLength(20);
    });
});
