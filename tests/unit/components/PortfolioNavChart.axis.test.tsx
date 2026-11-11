import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// Recharts no pinta los ticks de los ejes en jsdom (los grupos salen vacios:
// no hay medicion de texto), asi que el contrato del componente con los ejes
// se comprueba capturando las props que les pasa.
const captured: { yDomain?: unknown; xTick?: { fill?: string; fontSize?: number } } = {};

vi.mock('recharts', () => ({
    ResponsiveContainer: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
    AreaChart: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
    Area: () => null,
    Tooltip: () => null,
    XAxis: (props: { tick?: { fill?: string; fontSize?: number } }) => {
        captured.xTick = props.tick;
        return null;
    },
    YAxis: (props: { domain?: unknown }) => {
        captured.yDomain = props.domain;
        return null;
    },
}));

import PortfolioNavChart from '@/components/portfolio/PortfolioNavChart';
import { navYDomain } from '@/lib/portfolio/nav-domain';

const data = [
    { date: '2026-10-01', value: 100_000 },
    { date: '2026-10-02', value: 101_500 },
    { date: '2026-10-03', value: 99_800 },
];

describe('PortfolioNavChart (ejes)', () => {
    it('el eje Y usa el dominio proporcional de navYDomain, no 50 EUR fijos', () => {
        render(<PortfolioNavChart data={data} positive />);
        // Antes: ['dataMin - 50', 'dataMax + 50'] -> con NAV de ~100k la curva
        // llenaba todo el alto y una variacion del 1 % parecia un desplome.
        expect(captured.yDomain).toEqual(navYDomain([100_000, 101_500, 99_800]));
        expect(captured.yDomain).not.toEqual(['dataMin - 50', 'dataMax + 50']);
    });

    it('las etiquetas del eje X son legibles: tinta secundaria y al menos 11px', () => {
        render(<PortfolioNavChart data={data} positive />);
        // Antes #6b7280 a 10px: 3,9:1 sobre el fondo real del grafico
        // (#111111, medido en prod), bajo el AA 4,5:1. #a1a1aa es el
        // gray-500 de la paleta del repo (globals.css): 7,4:1.
        expect(captured.xTick?.fill).toBe('#a1a1aa');
        expect(captured.xTick?.fontSize).toBeGreaterThanOrEqual(11);
    });
});
