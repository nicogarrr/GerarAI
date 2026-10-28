import { describe, expect, it } from 'vitest';
import { NOT_VALUABLE, modelConditionState, researchValuability, visibleThesisRating } from '@/lib/research/coverage-state';

const good = { latest_thesis: { status: 'ok' }, model_summary: { status: 'ok', publishable: true }, valuation_summary: { status: 'ok' } };

describe('researchValuability', () => {
    it('todo en orden: revisar', () => {
        expect(researchValuability(good)).toBe('Revisar tesis y supuestos');
    });
    it('falta tesis o modelo, o modelo no publicable: no valorable', () => {
        expect(researchValuability({ ...good, latest_thesis: null })).toBe(NOT_VALUABLE);
        expect(researchValuability({ ...good, model_summary: null })).toBe(NOT_VALUABLE);
        expect(researchValuability({ ...good, model_summary: { status: 'ok', publishable: false } })).toBe(NOT_VALUABLE);
    });
    it.each(['insufficient_data', 'blocked', 'preview_only'])('estado %s en cualquiera de las tres capas bloquea', (s) => {
        expect(researchValuability({ ...good, latest_thesis: { status: s } })).toBe(NOT_VALUABLE);
        expect(researchValuability({ ...good, model_summary: { status: s, publishable: true } })).toBe(NOT_VALUABLE);
        expect(researchValuability({ ...good, valuation_summary: { status: s } })).toBe(NOT_VALUABLE);
    });
});

describe('modelConditionState', () => {
    const item = (over = {}) => ({ id: 'x', value: 1, comparison: 1, status: 'ok', ...over });
    it('fuera de rango manda sobre todo', () => {
        expect(modelConditionState(item({ status: 'out_of_bounds', value: null }), true)).toBe('Fuera de rango');
    });
    it('ROIC vs WACC sin fuente o sin comparación: pendiente por WACC', () => {
        expect(modelConditionState(item({ id: 'roic_above_wacc' }), false)).toBe('Pendiente: WACC sin datos');
        expect(modelConditionState(item({ id: 'roic_above_wacc', comparison: null }), true)).toBe('Pendiente: WACC sin datos');
        expect(modelConditionState(item({ id: 'roic_above_wacc', comparison: NaN }), true)).toBe('Pendiente: WACC sin datos');
        expect(modelConditionState(item({ id: 'roic_above_wacc' }), true)).toBe('Pendiente de contrastar');
    });
    it('margen FCF por debajo de -100 % no se acepta', () => {
        expect(modelConditionState(item({ id: 'fcf_margin', value: -1.5 }), true)).toBe('No cumplida: margen FCF fuera de rango');
        expect(modelConditionState(item({ id: 'fcf_margin', value: -1 }), true)).toBe('Pendiente de contrastar');
    });
    it('valor ausente, no finito o bloqueado: falta evidencia', () => {
        expect(modelConditionState(item({ value: null }), true)).toBe('Pendiente: falta evidencia');
        expect(modelConditionState(item({ value: Infinity }), true)).toBe('Pendiente: falta evidencia');
        expect(modelConditionState(item({ status: 'blocked_no_data' }), true)).toBe('Pendiente: falta evidencia');
    });
});

describe('visibleThesisRating', () => {
    it('sin rating -> null', () => {
        expect(visibleThesisRating(null, good)).toBeNull();
        expect(visibleThesisRating('', good)).toBeNull();
    });
    it('un veredicto de valoración se oculta si no es valorable (no vender "barata" sin evidencia)', () => {
        const blocked = { ...good, latest_thesis: null };
        expect(visibleThesisRating('cheap', blocked)).toBeNull();
        expect(visibleThesisRating('attractive', good)).toBe('attractive');
    });
    it('un rating que no es veredicto de valoración se mantiene', () => {
        expect(visibleThesisRating('hold', { ...good, latest_thesis: null })).toBe('hold');
    });
});
