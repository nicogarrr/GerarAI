import { describe, expect, it } from 'vitest';
import { researchErrorDetail } from '@/lib/research/error-detail';

describe('researchErrorDetail', () => {
    it('payload no objeto: usa el respaldo', () => {
        for (const p of [null, undefined, 'x', 3]) expect(researchErrorDetail(p, 'fb')).toBe('fb');
    });
    it('detail en texto manda sobre message', () => {
        expect(researchErrorDetail({ detail: 'Ticker inexistente', message: 'm' }, 'fb')).toBe('Ticker inexistente');
    });
    it('detail vacío o solo espacios cae a message y luego a respaldo', () => {
        expect(researchErrorDetail({ detail: '  ', message: 'm' }, 'fb')).toBe('m');
        expect(researchErrorDetail({ detail: '', message: '' }, 'fb')).toBe('fb');
    });
    it('errores de validación (lista): nombra campos sin prefijos body/query y sin duplicados', () => {
        const out = researchErrorDetail({ detail: [
            { loc: ['body', 'quantity'], msg: 'x' }, { loc: ['body', 'quantity'], msg: 'y' }, { loc: ['query', 'price'] },
        ] }, 'fb');
        expect(out).toBe('Datos no válidos en: quantity, price. Revisa esos campos y vuelve a intentarlo.');
    });
    it('lista sin campos identificables: mensaje genérico, nunca el JSON crudo', () => {
        const out = researchErrorDetail({ detail: [{ loc: ['body'] }, null, { loc: 'x' }, { loc: ['body', ' ', 3] }] }, 'fb');
        expect(out).toMatch(/rechazó los datos enviados/);
    });
    it('toma el último segmento con nombre de una ruta anidada', () => {
        expect(researchErrorDetail({ detail: [{ loc: ['body', 'items', 0, 'ticker'] }] }, 'fb')).toContain('ticker');
    });
    it('detail objeto con message o detail anidado', () => {
        expect(researchErrorDetail({ detail: { message: 'anidado' } }, 'fb')).toBe('anidado');
        expect(researchErrorDetail({ detail: { detail: 'otro' } }, 'fb')).toBe('otro');
        expect(researchErrorDetail({ detail: {} }, 'fb')).toBe('fb');
    });
});
