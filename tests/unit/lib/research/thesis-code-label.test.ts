// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { thesisCodeLabel } from '@/lib/research/thesis-code-label';

describe('thesisCodeLabel', () => {
    it('traduce identificadores conocidos', () => {
        expect(thesisCodeLabel('insufficient_data')).toBe('datos insuficientes');
        expect(thesisCodeLabel('unassigned')).toBe('sin asignar');
        expect(thesisCodeLabel('n/a')).toBe('no disponible');
    });
    it('cae a las etiquetas de métricas y del marco cuando aplica', () => {
        expect(thesisCodeLabel('roe')).toBe('ROE');
        expect(thesisCodeLabel('book_value')).toBe('valor contable');
    });
    it('lo que no es identificador standalone se devuelve intacto (URLs, prosa, código)', () => {
        expect(thesisCodeLabel('El PER es 15')).toBe('El PER es 15');
        expect(thesisCodeLabel('Revenue')).toBe('Revenue');
    });
    it('un identificador desconocido se muestra crudo: nunca se inventa lectura', () => {
        expect(thesisCodeLabel('clave_inexistente_zz9')).toBe('clave_inexistente_zz9');
    });
});
