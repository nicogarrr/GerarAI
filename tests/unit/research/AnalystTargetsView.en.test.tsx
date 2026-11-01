import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AnalystTargetsView } from '@/components/research/AnalystTargetsView';
import { LocaleProvider } from '@/lib/i18n/client';
import type { components } from '@/lib/research/openapi.generated';

const data = {
  status: 'available', currency: 'GBP', consensus: { median: 78, mean: 74, low: 42, high: 108 },
  rows: Array.from({ length: 7 }, (_, i) => ({ firm: `Firm ${i + 1}`, date: '2026-10-23', price_target: 55, prior_target: 50, rating: 'Overweight', upside_percent: 10 })),
  source: 'x', source_url: null, fetched_at: 1793120400, reference_price: 50,
} as components['schemas']['AnalystTargets'];

describe('analyst price targets in English', () => {
  it('headings, consensus, table, paging and footer in English', () => {
    render(<LocaleProvider locale="en"><AnalystTargetsView data={data} currency="USD" /></LocaleProvider>);
    expect(screen.getByText('Analyst price targets')).toBeInTheDocument();
    expect(screen.getByText('Targets in GBP: the stock page quotes in USD.')).toBeInTheDocument();
    expect(screen.getByText(/^Aggregate analyst consensus: median/)).toBeInTheDocument();
    expect(screen.getByText('Page 1 of 2')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Rating' })).toBeInTheDocument();
    expect(screen.getAllByText('Overweight').length).toBeGreaterThan(0);
    expect(screen.getByText(/Fetched on/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByRole('button', { name: 'Previous' })).not.toBeDisabled();
    expect(screen.queryByText(/Sobreponderar|Consenso|Página|Obtenido/)).not.toBeInTheDocument();
  });
});
