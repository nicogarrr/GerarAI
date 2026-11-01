import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AnalystTargetsSection } from '@/components/research/AnalystTargetsSection';
import { researchRequest } from '@/lib/research/client';

vi.mock('@/lib/research/client', () => ({ researchRequest: vi.fn() }));
const response = {
    status: 'available', currency: null, consensus: { median: 78, mean: 74.68, low: 42.5, high: 108 },
    rows: [{ firm: 'Fixture', date: '2026-10-23', price_target: 55.7, prior_target: 50.8, rating: 'Buy', upside_percent: 30.1 }],
    source: 'Yahoo Finance', source_url: null, fetched_at: 1793120400, reference_price: 42.8,
};

describe('analyst target units come from their response, not the company master', () => {
    it.each([null, '', '   '])('does not label unknown provider currency %j as GBP', async (currency) => {
        vi.mocked(researchRequest).mockResolvedValue({ ...response, currency });
        render(await AnalystTargetsSection({ symbol: 'FIXTURE.L', currency: 'GBP' }));
        const section = screen.getByTestId('analyst-targets');
        expect(section).toHaveTextContent('Divisa no declarada: importes sin unidad verificada y potencial N/D.');
        expect(section).not.toHaveTextContent('GBP');
        expect(section).not.toHaveTextContent('£');
        expect(section).not.toHaveTextContent('30,1');
        expect(screen.getAllByText('55,70')).toHaveLength(2);
    });
    it('keeps the provider declared minor unit even when the master says GBP', async () => {
        vi.mocked(researchRequest).mockResolvedValue({ ...response, currency: 'GBX' });
        render(await AnalystTargetsSection({ symbol: 'FIXTURE.L', currency: 'GBP' }));
        expect(screen.getByTestId('analyst-targets')).toHaveTextContent('GBX');
        expect(screen.getByTestId('analyst-targets')).not.toHaveTextContent('£');
        expect(screen.getByTestId('analyst-targets')).toHaveTextContent('30,1');
    });
});
