import { render, screen } from '@testing-library/react';
import { renderToStaticMarkup } from 'react-dom/server';
import { writeFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
vi.mock('@/lib/research/client', () => ({ researchRequest: vi.fn(async () => ({
  status: 'available', currency: 'USD', consensus: { median: 78, mean: 74.68, low: 42.5, high: 108 },
  rows: [{ firm: 'Scotiabank', date: '2026-10-23', price_target: 55.7, prior_target: 50.8, rating: 'Outperform', upside_percent: 30.1 }],
  source: 'Yahoo Finance', source_url: null, fetched_at: 1793120400, reference_price: 42.8,
})) }));
import { AnalystTargetsSection } from '@/components/research/AnalystTargetsSection';

describe('analyst target heading inside mobile accordion', () => {
  it('keeps an accessible heading and the desktop heading, without a second visible mobile title', async () => {
    const section = await AnalystTargetsSection({ symbol: 'DEMO', currency: 'USD' });
    render(section);
    const heading = screen.getByRole('heading', { name: 'Precios objetivo de analistas' });
    expect(heading).toHaveClass('sr-only', 'md:not-sr-only');
    expect(screen.getByRole('region', { name: 'Precios objetivo de analistas' })).toBeInTheDocument();
    expect(screen.getByTestId('analyst-consensus-note')).toHaveTextContent('Cifra publicada por Yahoo');
    expect(screen.getAllByText('Scotiabank')).toHaveLength(2); // mobile list + desktop table unchanged
    if (process.env.QA_HTML) writeFileSync(process.env.QA_HTML, renderToStaticMarkup(section));
  });
});
