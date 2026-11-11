import { describe, expect, it } from 'vitest';
import { navYDomain } from '@/lib/portfolio/nav-domain';

describe('navYDomain', () => {
    it('deja un margen del 5 % del rango a cada lado', () => {
        // Rango 101.000-100.000 = 1.000 -> margen 50 a cada lado.
        expect(navYDomain([100_000, 101_000])).toEqual([99_950, 101_050]);
    });

    it('escala con carteras grandes: no aplana la curva contra los bordes', () => {
        const [min, max] = navYDomain([24_000, 24_657.77]);
        // Margen = 5 % de 657,77 = 32,8885: visible, no las 50 unidades fijas
        // de antes (que con este rango apenas se notaban pero con 100k de
        // cartera hacian que la curva llenara todo el alto).
        expect(min).toBeCloseTo(24_000 - 657.77 * 0.05, 6);
        expect(max).toBeCloseTo(24_657.77 + 657.77 * 0.05, 6);
    });

    it('serie plana: dominio no degenerado (ancho > 0)', () => {
        const [min, max] = navYDomain([100_000, 100_000, 100_000]);
        expect(max - min).toBeGreaterThan(0);
        expect(min).toBeLessThan(100_000);
        expect(max).toBeGreaterThan(100_000);
    });

    it('serie plana en cero: sigue sin degenerar', () => {
        const [min, max] = navYDomain([0, 0]);
        expect(max - min).toBeGreaterThan(0);
    });

    it('sin puntos: dominio de reserva valido', () => {
        const [min, max] = navYDomain([]);
        expect(max).toBeGreaterThan(min);
    });

    it('un solo punto: dominio no degenerado alrededor del valor', () => {
        const [min, max] = navYDomain([42]);
        expect(min).toBeLessThan(42);
        expect(max).toBeGreaterThan(42);
    });
});
