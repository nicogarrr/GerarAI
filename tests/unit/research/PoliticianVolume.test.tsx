import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { PoliticianCardView } from '@/components/research/PoliticianCard';
import type { PoliticianCard } from '@/lib/research/insiders-politicians';

const card: PoliticianCard = {
  member_key: 'house:XX01:example', member: 'Ejemplo de prueba', chamber: 'house', state: 'XX', district: '01', state_district: 'XX01',
  party: null, bioguide: null, filings: 1, scanned_filings: 0, trades: 2, tickers: 0, top_tickers: [],
  last_trade: null, last_filing: null, late: 0, late_over_30: 0, on_time_pct: null, volume_min: 1001, volume_max: 15000,
};

describe('importes desconocidos de políticos', () => {
  it.each(['es', 'en'] as const)('no muestra un subtotal como total (%s)', (locale) => {
    render(<PoliticianCardView locale={locale} card={{ ...card, volume_unknown_trades: 1 }} />);
    expect(screen.getByText(locale === 'es' ? /Volumen parcial/ : /Partial volume/)).toBeInTheDocument();
    expect(screen.getByText(locale === 'es' ? /Operaciones sin importe verificable: 1/ : /Trades without a verifiable amount: 1/)).toBeInTheDocument();
  });
  it.each(['es', 'en'] as const)('todos desconocidos no se convierten en cero (%s)', (locale) => {
    render(<PoliticianCardView locale={locale} card={{ ...card, volume_min: 0, volume_max: 0, volume_unknown_trades: 2 }} />);
    expect(screen.getByText(locale === 'es' ? /Volumen no disponible/ : /Volume unavailable/)).toBeInTheDocument();
    expect(screen.queryByText(/\$0|0\s*\$/)).toBeNull();
  });
  it('conserva el rango completo cuando todos tienen importe', () => {
    render(<PoliticianCardView card={{ ...card, volume_unknown_trades: 0 }} />);
    expect(screen.getByText(/Volumen declarado:/)).toBeInTheDocument();
    expect(screen.queryByText(/Volumen parcial/)).toBeNull();
  });
});
