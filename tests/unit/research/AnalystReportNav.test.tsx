import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AnalystReportNav, publishedNav, type PublishedNav } from '@/components/research/AnalystReportNav';
import { createFormatters } from '@/lib/format';
import { translateMessage } from '@/lib/i18n/translate';

const t = ((key: string, vars?: Record<string, string | number>) => translateMessage('es', key, vars)) as Parameters<typeof AnalystReportNav>[0]['t'];
const fmt = createFormatters('es');

// Georgia Capital, RNS de resultados del 1S 2026 (FCA NSM): «NAV per share, GBP 50.10».
const nav: PublishedNav = {
  nav_per_share: 50.1, currency: 'GBP', price: 42, price_currency: 'GBP', price_date: '2026-11-06',
  discount: 42 / 50.1 - 1, discount_reason: null, formula: 'descuento = precio / NAV por acción publicado − 1',
  source: { title: 'Half-year Financial Report', url: 'https://data.fca.org.uk/artefacts/NSM/RNS/h1-2026.html', published: '2026-08-04', period_end: null, quote: 'NAV per share, GBP 50.10 43.34' },
  other_currencies: [{ value: 175.12, currency: 'GEL' }],
};

describe('AnalystReportNav', () => {
  it('pinta el NAV publicado, el descuento y la fuente enlazada con su cita', () => {
    render(<dl><AnalystReportNav nav={nav} t={t} fmt={fmt} /></dl>);
    const row = screen.getByTestId('informe-nav');
    expect(row.textContent).toContain('NAV por acción');
    expect(row.textContent).toMatch(/50,10/);
    expect(row.textContent).toMatch(/descuento del 16,2/);
    const link = screen.getByRole('link', { name: 'Half-year Financial Report' });
    expect(link.getAttribute('href')).toBe('https://data.fca.org.uk/artefacts/NSM/RNS/h1-2026.html');
    expect(row.textContent).toContain('«NAV per share, GBP 50.10 43.34»');
  });

  it('sin divisa común no inventa el descuento, y un enlace no http no se pinta', () => {
    render(<dl><AnalystReportNav nav={{ ...nav, discount: null, discount_reason: 'currency_mismatch', source: { ...nav.source, url: 'javascript:alert(1)' } }} t={t} fmt={fmt} /></dl>);
    expect(screen.getByTestId('informe-nav').textContent).toContain('no hay tipo de cambio citado');
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('un informe sin bloque nav no pinta nada', () => {
    expect(publishedNav({ market: {} })).toBeNull();
    expect(publishedNav(undefined)).toBeNull();
    const { container } = render(<dl><AnalystReportNav nav={publishedNav({})} t={t} fmt={fmt} /></dl>);
    expect(container.querySelector('[data-testid="informe-nav"]')).toBeNull();
  });
});
