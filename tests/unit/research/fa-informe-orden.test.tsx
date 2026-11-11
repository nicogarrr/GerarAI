import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { AnalystReportView } from '@/components/research/AnalystReportView';
import { evidenceValue, orderedSummaries } from '@/components/research/ValuationSummaryGrid';
import { createFormatters } from '@/lib/format';
import { createTranslator } from '@/lib/i18n/translate';
import type { ReportInputs } from '@/lib/research/analyst-report';
import type { ValuationSummary } from '@/lib/research/valuation-summary';
import fixture from './analyst-report-asts.fixture.json';

const base = fixture as unknown as ReportInputs;
const view = (patch: Partial<ReportInputs> = {}) => render(<AnalystReportView data={{ ...base, ...patch }} t={createTranslator('es')} fmt={createFormatters('es')} locale="es" />);

describe('orden de lectura del Informe', () => {
  it('resumen y riesgos van justo tras la cabecera; mercado y tablas de cifras después de la valoración', () => {
    view();
    const ids = [...screen.getByTestId('analyst-report').querySelectorAll('section[aria-labelledby]')].map((s) => s.getAttribute('aria-labelledby'));
    expect(ids.indexOf('informe-resumen')).toBe(0);
    expect(ids.indexOf('informe-riesgos')).toBe(1);
    expect(ids.indexOf('informe-valoracion')).toBeLessThan(ids.indexOf('informe-mercado'));
    expect(ids.indexOf('informe-mercado')).toBeLessThan(ids.indexOf('informe-estimaciones'));
  });
  it('sin estimaciones propias no se repite el aviso «Supuestos del usuario…»', () => {
    view({ sotp: null });
    expect(screen.getByTestId('informe-user-estimates').textContent).not.toContain('no validados contra histórico');
  });
});

describe('resumen de valoración: evidencias legibles y orden de la lista', () => {
  const fmt = createFormatters('es');
  it('importes compactos con divisa, por acción con 2 decimales, acciones compactas', () => {
    expect(evidenceValue(391035000000, 'USD', fmt)).toBe(fmt.formatMoneyCompact(391035000000, 'USD'));
    expect(evidenceValue(391035000000, 'USD', fmt)).not.toContain('391.035.000.000');
    expect(evidenceValue(6.11, 'USD/share', fmt)).toBe(fmt.formatMoney(6.11, 'USD', { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
    expect(evidenceValue(15204137000, 'shares', fmt)).toBe(fmt.formatCompact(15204137000));
    expect(evidenceValue(0.25, 'pure', fmt)).toBe('0,25');
  });
  it('las tarjetas siguen el orden de la watchlist, no el del backend', () => {
    const item = (ticker: string) => ({ ticker }) as unknown as ValuationSummary;
    const items = { AAPL: item('AAPL'), MSFT: item('MSFT'), TSM: item('TSM') };
    const quotes = [{ symbol: 'tsm', price: 1, currency: 'USD' }, { symbol: 'MSFT', price: 1, currency: 'USD' }, { symbol: 'AAPL', price: 1, currency: 'USD' }];
    expect(orderedSummaries(items, quotes).map((i) => i.ticker)).toEqual(['TSM', 'MSFT', 'AAPL']);
  });
});
