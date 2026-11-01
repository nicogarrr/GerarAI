import React, { type ComponentProps, type ReactElement, type ReactNode } from 'react';
import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// Props que el gráfico pasa a cada pieza de recharts (mockeada abajo).
type CapturedTooltip = { formatter: (value: number) => [string, string]; content: ReactElement<{ currency?: string }> };
type Captured = {
    tooltip: CapturedTooltip | null;
    area: { stroke?: string } | null;
    stops: string[];
    cells: Array<{ fill?: string }>;
    pie: { nameKey?: string; children?: ReactNode } | null;
};

const cap = vi.hoisted((): Captured => ({ tooltip: null, area: null, stops: [], cells: [], pie: null }));

vi.mock('recharts', () => {
    const P = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
    return {
        ResponsiveContainer: P,
        AreaChart: P,
        PieChart: P,
        XAxis: () => null,
        YAxis: () => null,
        Tooltip: (p: CapturedTooltip) => { cap.tooltip = p; return null; },
        Area: (p: { stroke?: string }) => { cap.area = p; return null; },
        Pie: (p: { nameKey?: string; children?: ReactNode }) => { cap.pie = p; return <div>{p.children}</div>; },
        Cell: (p: { fill?: string }) => { cap.cells.push(p); return null; },
    };
});

import PortfolioNavChart from '@/components/portfolio/PortfolioNavChart';
import PortfolioAllocationChart, { COLORS } from '@/components/portfolio/PortfolioAllocationChart';

describe('PortfolioNavChart', () => {
    const data = [{ date: '2026-01-01', value: 100 }, { date: '2026-01-02', value: 110 }];

    it('usa verde si la cartera es positiva y rojo si no', () => {
        render(<PortfolioNavChart data={data} positive />);
        expect(cap.area?.stroke).toBe('#14b8a6');
        render(<PortfolioNavChart data={data} positive={false} />);
        expect(cap.area?.stroke).toBe('#ef4444');
    });

    it('el tooltip formatea el valor en la divisa base indicada', () => {
        render(<PortfolioNavChart data={data} positive currency="EUR" />);
        const [text, label] = cap.tooltip!.formatter(1234.5);
        expect(text).toMatch(/1\.234,50\s?€/);
        expect(label).toBe('Valor');
    });

    it('por defecto formatea en USD', () => {
        render(<PortfolioNavChart data={data} positive />);
        expect(cap.tooltip!.formatter(10)[0]).toContain('$');
    });
});

describe('PortfolioAllocationChart', () => {
    it('una celda por posicion y colores cíclicos al superar la paleta', () => {
        cap.cells = [];
        const n = COLORS.length + 2;
        const chartData = Array.from({ length: n }, (_, i) => ({ symbol: `S${i}`, value: i + 1 })) as ComponentProps<typeof PortfolioAllocationChart>['chartData'];
        render(<PortfolioAllocationChart chartData={chartData} currency="EUR" />);
        expect(cap.cells).toHaveLength(n);
        expect(cap.cells[COLORS.length].fill).toBe(COLORS[0]);
        expect(cap.cells[COLORS.length + 1].fill).toBe(COLORS[1]);
        expect(cap.pie?.nameKey).toBe('symbol');
        expect(cap.tooltip?.content.props.currency).toBe('EUR');
    });

    it('sin datos no renderiza celdas', () => {
        cap.cells = [];
        render(<PortfolioAllocationChart chartData={[]} />);
        expect(cap.cells).toHaveLength(0);
    });
});
