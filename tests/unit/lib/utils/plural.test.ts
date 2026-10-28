// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { plural } from '@/lib/utils/plural';

describe('plural', () => {
    it('1 va en singular', () => {
        expect(plural(1, 'escaneado', 'escaneados')).toBe('1 escaneado');
    });
    it('0 y cualquier otro número van en plural', () => {
        expect(plural(0, 'escaneado', 'escaneados')).toBe('0 escaneados');
        expect(plural(20, 'escaneado', 'escaneados')).toBe('20 escaneados');
    });
    it('el número lleva formato es-ES con separador de miles', () => {
        expect(plural(1234, 'carta', 'cartas')).toBe('1.234 cartas');
    });
});
