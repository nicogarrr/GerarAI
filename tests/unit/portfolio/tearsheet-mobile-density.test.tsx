import { readFileSync } from 'node:fs';
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';

const src = (p: string) => readFileSync(p, 'utf8');

import PortfolioTearsheet from '@/components/portfolio/PortfolioTearsheet';
const tearsheet: any = {
    status: 'ok', exposure: null, qualification: null, trace: {},
    metrics: {
        sharpe: 1.48, max_drawdown: -0.1346, win_rate: 0.5647,
        n_observations: 642, cumulative_return: 0.32, best_day: 0.05, worst_day: -0.04,
    },
};

// /portfolio 390x844 y desktop: dos solapes medidos 17-nov-2026 en dev con
// datos reales sembrados (Sharpe 1,48 / -13,46 % / 56,47 %).
describe('portfolio density and FAB clearance', () => {
    it('keeps tearsheet values apart at 390px (gradual size + tight gap only below sm)', () => {
        const t = src('components/portfolio/PortfolioTearsheet.tsx');
        expect(t).toContain('grid grid-cols-3 gap-2 sm:gap-4');
        expect(t).toContain('text-center p-2 sm:p-3 bg-gray-900/50 rounded-lg');
        expect(t).toContain('text-base min-[420px]:text-lg sm:text-2xl font-bold tracking-tight break-words text-gray-100');
    });
    it('tearsheet lleva las clases graduales al DOM y pinta los valores reales', () => {
        const { container } = render(<PortfolioTearsheet tearsheet={tearsheet} />);
        const grid = container.querySelector('.grid.grid-cols-3');
        expect(grid?.className).toContain('gap-2 sm:gap-4');
        const values = Array.from(grid!.querySelectorAll('.tracking-tight'));
        expect(values).toHaveLength(3);
        for (const v of values) expect(v.className).toContain('text-base min-[420px]:text-lg sm:text-2xl');
        expect(container.textContent).toContain('1,48');
        expect(container.textContent).toContain('-13,46');
        expect(container.textContent).toContain('56,47');
    });
    it('tearsheet sin datos degrada a aviso', () => {
        const { container } = render(<PortfolioTearsheet tearsheet={null} />);
        expect(container.querySelector('.grid.grid-cols-3')).toBeNull();
        expect(container.textContent).toContain('No hay retornos suficientes');
    });

});
