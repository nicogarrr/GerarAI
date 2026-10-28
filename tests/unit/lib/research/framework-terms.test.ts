import { describe, expect, it } from 'vitest';
import { frameworkLabel, frameworkTerm } from '@/lib/research/framework-terms';

describe('frameworkTerm', () => {
    it('término simple, sin importar mayúsculas ni espacios (se normaliza a snake_case)', () => {
        expect(frameworkTerm('ARPU')).toBe('ARPU');
        expect(frameworkTerm('  Book Value ')).toBe('valor contable');
        expect(frameworkTerm('book_value_per_share')).toBe('valor contable por acción');
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
