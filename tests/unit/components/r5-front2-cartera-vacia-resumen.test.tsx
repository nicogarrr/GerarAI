import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import PortfolioSummary from '@/components/portfolio/PortfolioSummary';
import type { PortfolioSummary as Summary } from '@/lib/actions/portfolio.actions';

const blank = {
    totalValue: 0, totalCost: 0, totalGain: 0, totalGainPercent: 0, holdings: [], equityValue: 0, cash: 0,
    baseCurrency: 'EUR', valuationHold: [], missingFx: [], status: 'ok',
} as unknown as Summary;

describe('cartera vacía: cada N/D de las tarjetas dice por qué', () => {
    it('las cuatro tarjetas en N/D llevan «Sin posiciones todavía»', () => {
        render(<PortfolioSummary summary={blank} />);
        expect(screen.getAllByText('N/D')).toHaveLength(4);
        expect(screen.getAllByText('Sin posiciones todavía')).toHaveLength(4);
    });
    it('con caja y sin posiciones: el valor es la caja y solo coste, G/P y rendimiento llevan el motivo', () => {
        render(<PortfolioSummary summary={{ ...blank, totalValue: 500, cash: 500 } as Summary} />);
        expect(screen.getAllByText('Sin posiciones todavía')).toHaveLength(3);
    });
});
