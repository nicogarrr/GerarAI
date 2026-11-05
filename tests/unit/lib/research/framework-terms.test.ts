import { describe, expect, it } from 'vitest';
import { frameworkLabel, frameworkTerm, methodLabel } from '@/lib/research/framework-terms';

describe('frameworkTerm', () => {
    it('término simple, sin importar mayúsculas ni espacios (se normaliza a snake_case)', () => {
        expect(frameworkTerm('ARPU')).toBe('ARPU');
        expect(frameworkTerm('  Book Value ')).toBe('valor contable');
        expect(frameworkTerm('book_value_per_share')).toBe('valor contable por acción');
    });
    it('modelo de valoración sin asignar: etiqueta ES, EN humaniza el slug', () => {
        expect(frameworkTerm('unassigned')).toBe('sin asignar');
        expect(frameworkTerm('unassigned', 'en')).toBe('unassigned');
    });
    it('término desconocido: null, no se inventa traducción', () => {
        expect(frameworkTerm('termino_inventado')).toBeNull();
        expect(frameworkTerm('')).toBeNull();
    });
    it('fórmulas con × y ÷ traducen cada parte y conservan el operador', () => {
        expect(frameworkTerm('backlog × book_value')).toBe('cartera de pedidos × valor contable');
        expect(frameworkTerm('backlog÷book_value')).toBe('cartera de pedidos ÷ valor contable');
    });
    it('"X per Y" dentro de una fórmula se traduce con "por"', () => {
        expect(frameworkTerm('backlog per bookings × advertising')).toBe('cartera de pedidos por reservas contratadas × publicidad');
    });
    it('una sola parte desconocida invalida toda la fórmula', () => {
        expect(frameworkTerm('backlog × zzz')).toBeNull();
        expect(frameworkTerm('backlog per zzz × advertising')).toBeNull();
    });
});

describe('frameworkLabel', () => {
    it('traduce etiqueta conocida y deja la desconocida tal cual', () => {
        expect(frameworkLabel('Space network / connectivity')).toBe('Red espacial / conectividad');
        expect(frameworkLabel('Algo nuevo')).toBe('Algo nuevo');
    });
});

describe('methodLabel · método de valoración persistida', () => {
    it('métodos conocidos llevan etiqueta, nunca el slug', () => {
        expect(methodLabel('unassigned')).toBe('sin asignar');
        expect(methodLabel('median_last_n_fiscal_years')).toBe('mediana de los últimos ejercicios');
        expect(methodLabel('fcff_dcf_multistage')).toBe('DCF multietapa');
        expect(methodLabel('median_last_n_fiscal_years', 'en')).toBe('median last n fiscal years');
    });

    it('método desconocido se humaniza, no se muestra el snake_case crudo', () => {
        expect(methodLabel('binary_search_reverse_dcf')).toBe('binary search reverse dcf');
        expect(methodLabel('binary_search_reverse_dcf', 'en')).toBe('binary search reverse dcf');
    });
});
