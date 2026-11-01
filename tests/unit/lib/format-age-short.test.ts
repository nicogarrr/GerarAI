import { describe, expect, it } from 'vitest';
import { formatAgeShort } from '@/lib/format';

const NOW = Date.UTC(2026, 10, 1, 12, 0, 0);
const secs = (horasAtras: number) => NOW / 1000 - horasAtras * 3600;

describe('formatAgeShort', () => {
    it('horas y días compactos estilo feed (es)', () => {
        expect(formatAgeShort(secs(22), NOW)).toBe('22 h');
        expect(formatAgeShort(secs(30), NOW)).toBe('1 d');
        expect(formatAgeShort(secs(24 * 5), NOW)).toBe('5 d');
        expect(formatAgeShort(NOW / 1000 - 120, NOW)).toBe('2 min');
        expect(formatAgeShort(NOW / 1000 - 10, NOW)).toBe('ahora');
    });
    it('en inglés sin espacio', () => {
        expect(formatAgeShort(secs(22), NOW, 'en')).toBe('22h');
        expect(formatAgeShort(secs(30), NOW, 'en')).toBe('1d');
    });
    it('más de 6 días o inválida: null (el caller pinta la fecha corta)', () => {
        expect(formatAgeShort(secs(24 * 7), NOW)).toBeNull();
        expect(formatAgeShort(0, NOW)).toBeNull();
        expect(formatAgeShort(null, NOW)).toBeNull();
        expect(formatAgeShort(Number.NaN, NOW)).toBeNull();
    });
});
