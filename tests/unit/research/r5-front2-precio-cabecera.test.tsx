import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';

import { AnalystReportView } from '@/components/research/AnalystReportView';
import DcaWatchCard from '@/components/watchlist/DcaWatchCard';
import { createFormatters } from '@/lib/format';
import { createTranslator } from '@/lib/i18n/translate';
import type { DcaWatchCardData } from '@/lib/dca/types';
import type { ReportInputs } from '@/lib/research/analyst-report';
import fixture from './analyst-report-asts.fixture.json';

// ASTS real (fixture del Informe): cierre 32,33 USD del 6-nov-2026; tarjeta DCA con currency USD.
const base = fixture as unknown as ReportInputs;
// Intl separa importe y divisa con un espacio duro: se compara el texto visible.
const n = (s: string | null | undefined) => (s ?? '').replace(/\s/g, ' ');
const view = (patch: Partial<ReportInputs> = {}, locale: 'es' | 'en' = 'es') =>
  render(<AnalystReportView data={{ ...base, ...patch }} t={createTranslator(locale)} fmt={createFormatters(locale)} locale={locale} />);

describe('Informe: el precio de la cabecera dice que es un cierre y de qué día', () => {
  it('rotula «Precio (cierre 6 nov)» en la cabecera y en datos de mercado', () => {
    view();
    expect(screen.getByTestId('informe-price-label').textContent).toBe('Precio (cierre 6 nov)');
    expect(n(screen.getByTestId('informe-price').textContent)).toBe('32,33 US$');
    expect(within(screen.getByTestId('informe-market')).getByText('Precio (cierre 6 nov)')).toBeTruthy();
  });
  it('en inglés también', () => {
    view({}, 'en');
    expect(screen.getByTestId('informe-price-label').textContent).toBe('Price (close Nov 6)');
  });
});

describe('una sola forma de escribir el dólar en la página: «US$»', () => {
  it('la tarjeta DCA pinta sus precios con la divisa en es-ES («US$»), no «USD»', () => {
    const card = {
      ...(base.card as DcaWatchCardData),
      currency_label: 'USD',
      current: { ...(base.card as DcaWatchCardData).current!, close_kind: 'live' as const },
      live: { used: true, price: 33.1, session: 'regular', timestamp: 1763044200, currency: 'USD' },
    } as DcaWatchCardData;
    render(<DcaWatchCard data={card} ti={createTranslator('es')} locale="es" />);
    const live = n(screen.getByTestId('dca-card-live').textContent);
    expect(live).toContain('33,10 US$');
    expect(live).not.toMatch(/\bUSD\b/);
  });
  it('el Informe completo no mezcla «USD» con «US$»', () => {
    const card = { ...(base.card as DcaWatchCardData), currency_label: 'USD' } as DcaWatchCardData;
    view({ card });
    const text = n(screen.getByTestId('analyst-report').textContent);
    expect(text).toContain('US$');
    expect(text).not.toMatch(/\d USD\b/);
  });
  it('sin divisa ISO reconocible conserva la etiqueta del backend (peniques)', () => {
    const card = { ...(base.card as DcaWatchCardData), currency: null, currency_label: 'GBX (peniques)' } as DcaWatchCardData;
    render(<DcaWatchCard data={card} ti={createTranslator('es')} locale="es" />);
    expect(screen.getByTestId('dca-card-change').textContent ?? '').toContain('GBX (peniques)');
  });
});

describe('volumen en corto N/D con su motivo', () => {
  it('sin consulta guardada: el motivo de la fuente', () => {
    view({ shorts: { ticker: 'ASTS', status: 'empty', fetched_at: null, reason: 'No hay consulta almacenada. Usa Actualizar para consultar la fuente pública.', data: null } });
    expect(screen.getByTestId('informe-short-volume').textContent).toContain('No hay consulta almacenada');
  });
  it('lectura fallida: lo dice en vez de un N/D mudo', () => {
    view({ shorts: null });
    expect(screen.getByTestId('informe-short-volume').textContent).toContain('No se pudo leer');
  });
  it('con datos pero sin volumen diario: lo dice', () => {
    view({ shorts: { ticker: 'ASTS', status: 'available', fetched_at: null, reason: null, data: { source: 'x', source_url: 'https://x', note: '', public_total_percent: 1.2 } } });
    expect(screen.getByTestId('informe-short-volume').textContent).toContain('volumen en corto diario');
  });
});
