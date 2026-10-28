/**
 * A 768px (md) las tarjetas de estrés iban a 3 columnas de ~155 px y los
 * valores nowrap de «Recuperación desde el pico» rebosaban la tarjeta y
 * la ventana (scrollW 805 > 768). La rejilla debe ser 2 columnas en md y
 * reservar las 3 columnas para xl, donde la tarjeta ya cabe.
 */
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import HistoricalStressView from '@/components/historical-stress/HistoricalStressView';
import type { HistoricalStressReport, StressWindow } from '@/types/historical-stress';

const window2008: StressWindow = {
    year: 2008,
    status: 'calculated',
    return: -0.569,
    max_drawdown: -0.594,
    peak_date: '2007-12-31',
    trough_date: '2008-11-20',
    start_date: '2007-12-31',
    end_date: '2008-12-31',
    observations: 253,
    recovery_date: '2023-06-02',
    recovery_days: 515,
    recovery_status: 'recovered',
    last_observation: '2023-06-02',
};

const report: HistoricalStressReport = {
    generated_at: '2026-10-28T00:00:00Z',
    mode: 'portfolio',
    data_kind: 'adjusted_close',
    portfolio: [window2008],
    companies: [{
        ticker: 'AAPL',
        weight: 0.5,
        weight_as_of: '2026-10-01',
        source: 'Yahoo Finance',
        source_url: null,
        fetched_at: '2026-10-28',
        currency: 'USD',
        windows: [window2008],
    }],
};

describe('HistoricalStressView: rejilla de tarjetas', () => {
    it('2 columnas en md y 3 solo desde xl (tanto cartera como compañía)', () => {
        const { container } = render(<HistoricalStressView report={report} />);
        const grids = Array.from(container.querySelectorAll('div.grid'));
        expect(grids.length).toBeGreaterThanOrEqual(2);
        for (const grid of grids) {
            expect(grid.className).toContain('md:grid-cols-2');
            expect(grid.className).toContain('xl:grid-cols-3');
            expect(grid.className).not.toContain('md:grid-cols-3');
        }
    });
});
