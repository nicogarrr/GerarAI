import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';

import { AnalystReportView } from '@/components/research/AnalystReportView';
import { createFormatters } from '@/lib/format';
import { createTranslator } from '@/lib/i18n/translate';
import { engineRangeFrom, fairValueRange, thesisRisks, userEstimates, vsPrice, reportVsPrice, type ReportInputs } from '@/lib/research/analyst-report';
import type { SotpResponse } from '@/lib/research/sotp';
import fixture from './analyst-report-asts.fixture.json';
import sotpFixture from './sotp-asts.fixture.json';

// ASTS: mercado y cifras reales salen del endpoint sobre SEC + cierres (ver «_fuente»).
const data = { ...(fixture as unknown as ReportInputs), sotp: sotpFixture as unknown as SotpResponse };

function view(locale: 'es' | 'en' = 'es', patch: Partial<ReportInputs> = {}) {
  return render(<AnalystReportView data={{ ...data, ...patch }} t={createTranslator(locale)} fmt={createFormatters(locale)} locale={locale} />);
}

describe('helpers del informe', () => {
  it('el rango de la cabecera es el de la tesis si el valor justo sale de ella; si no, el del motor', () => {
    const thesis = { version: 3, status: 'published', bear_value: '18.5', bull_value: 60 };
    expect(fairValueRange({ value: 24.4, currency: 'USD', label: 'Tesis publicada v3', as_of: null, publishable: true }, thesis, { low: 10, high: 20 })).toEqual({ low: 18.5, high: 60, source: 'thesis' });
    expect(fairValueRange({ value: 15, currency: 'USD', label: 'Motor DCF', as_of: null, publishable: true }, thesis, { low: 10, high: 20 })).toEqual({ low: 10, high: 20, source: 'engine' });
    expect(fairValueRange(null, { version: 1, status: 'published', bear_value: null, bull_value: 5 }, null)).toBeNull();
    expect(engineRangeFrom({ low: 1, high: 2 })).toEqual({ low: 1, high: 2 });
    expect(engineRangeFrom({ low: null, high: 2 })).toBeNull();
  });

  it('riesgos = criterios de invalidación + secciones de riesgos; estimaciones del usuario = su desglose', () => {
    const r = thesisRisks({ version: 1, status: 'published', invalidation_criteria: ['A', ' '] }, [{ titulo: 'Riesgos clave', parrafos: ['x'] }, { titulo: 'Negocio', parrafos: ['y'] }]);
    expect(r.criteria).toEqual(['A']);
    expect(r.sections.map((s) => s.titulo)).toEqual(['Riesgos clave']);
    expect(userEstimates(sotpFixture as unknown as SotpResponse)).toMatchObject({ year: 2030, revenue: 6320, ebitda: 5722, author: 'Nico', origin: 'example' });
    expect(userEstimates(null)).toBeNull();
    expect(vsPrice(24.4, 32.33)).toBeCloseTo(-0.2453, 3);
    expect(vsPrice(10, 0)).toBeNull();
  });
});

describe('AnalystReportView (ASTS)', () => {
  it('cabecera: nivel DCA con su color, valor justo frente al precio y que no es una recomendación', () => {
    view();
    const chip = screen.getByTestId('informe-dca');
    expect(chip.textContent).toBe('4X DCA');
    expect(chip.getAttribute('style')).toContain('background-color: rgb(180, 0, 255)');
    expect(chip.parentElement?.textContent).toContain('Zona de compra extrema · 5 meses en zona');
    expect(screen.getByTestId('informe-fair').textContent).toContain('24,40');
    expect(screen.getByTestId('analyst-report').querySelector('header')?.textContent).toMatch(/valor justo [−-]24,5\s?% vs precio/);
    expect(screen.getByText(/no es una recomendación de compra o venta/)).toBeTruthy();
    expect(screen.getByTestId('informe-range').textContent).toBe('N/D');
  });

  it('datos de mercado y cifras reales, con el Q4 derivado marcado y sin mezclar estimaciones', () => {
    view();
    const market = screen.getByTestId('informe-market');
    expect(market.textContent).toContain('Con acciones diluidas');
    expect(market.textContent).toContain('Media de 63 sesiones');
    expect(market.textContent).toContain('Capitalización + deuda − caja');
    expect(market.textContent).toMatch(/30,20.*133,09/);
    const quarterly = screen.getByRole('region', { name: 'Por trimestre (reales)' });
    expect(within(quarterly).getByText(/^Q4 · /)).toBeTruthy();
    expect(quarterly.textContent).toContain('¹');
    const mine = screen.getByTestId('informe-user-estimates');
    expect(mine.textContent).toContain('Estimaciones de Nico');
    expect(mine.textContent).toContain('2030E: ingresos 6.320 M, EBITDA 5.722 M');
    expect(mine.textContent).toContain('Supuestos del usuario, no validados contra histórico.');
  });

  it('tesis, honestidad, desglose sin editor, riesgos y tesis completa', () => {
    view();
    expect(screen.getByTestId('informe-key-points').textContent).toContain('Resultados del 3T 2026');
    const honesty = screen.getByTestId('informe-honesty');
    expect(honesty.textContent).toContain('Sin valor justo fiable');
    // La tasa base va una vez, dentro del desglose; sin desglose, en la lista de honestidad.
    expect(honesty.textContent).not.toContain('Punto de partida');
    expect(screen.getByTestId('sotp-base-rate').textContent).toContain('Punto de partida');
    expect(screen.getByTestId('sotp-total').textContent).toContain('155,82');
    expect(screen.queryByRole('button', { name: /Guardar/ })).toBeNull();
    expect(screen.getByTestId('informe-risk-criteria').textContent).toContain('Dilución por encima de 480 M');
    expect(screen.getByText('Tesis completa')).toBeTruthy();
    expect(screen.getByText(/Bloque C: balance/)).toBeTruthy();
  });

  it('sin datos, cada caja lo dice y el informe se pinta igual', () => {
    view('es', { report: null, card: null, fair: null, thesis: null, sotp: null, keyStats: null, honesty: { trackRecord: null, sbc: null, baseRate: null, impliedGrowth: null } });
    expect(screen.getByText('No hay tesis publicada para esta empresa.')).toBeTruthy();
    expect(screen.getByText('Aún no hay estimaciones tuyas: añádelas en el desglose por partes.')).toBeTruthy();
    expect(screen.getByTestId('informe-fair').textContent).toBe('Sin valor justo fiable');
  });

  it('sin desglose, la tasa base sale en la lista de honestidad', () => {
    view('es', { sotp: null });
    expect(screen.getByTestId('informe-honesty').textContent).toContain('Punto de partida');
  });

  it('en inglés', () => {
    view('en');
    expect(screen.getByText('Market data')).toBeTruthy();
    expect(screen.getByText(/not a buy or sell recommendation/)).toBeTruthy();
  });
});


describe('informe: currencies belong to each figure', () => {
  it('normalizes GBp/GBX against GBP without mixing USD or unlabelled figures', () => {
    expect(reportVsPrice(50, 'GBP', 4255, 'GBp')).toBeCloseTo(50 / 42.55 - 1);
    expect(reportVsPrice(50, 'GBP', 4255, 'GBX')).toBeCloseTo(50 / 42.55 - 1);
    expect(reportVsPrice(50, 'USD', 4255, 'GBp')).toBeNull();
    expect(reportVsPrice(50, null, 40, 'USD')).toBeNull();
    expect(reportVsPrice(50, 'USD', 40, 'USD')).toBe(0.25);
  });

  it('does not label a DCA card price with a borrowed currency', () => {
    const report = structuredClone(data.report!);
    report.market.price = null;
    view('es', { report });
    const header = screen.getByTestId('analyst-report').querySelector('header')!;
    expect(header.textContent).toContain('valor justo N/D vs precio');
  });

  it('engine range currency is independent of the fair value and unknown units stay N/D', () => {
    expect(engineRangeFrom({ low: 40, high: 60, currency: 'GBP' })).toEqual({ low: 40, high: 60, currency: 'GBP' });
    view('es', { fair: { ...data.fair!, value: 50, currency: 'USD' }, thesis: null, engineRange: { low: 40, high: 60, currency: 'GBP' } });
    expect(screen.getByTestId('informe-range').textContent).toContain('GBP');
    expect(screen.getByTestId('informe-range').textContent).not.toContain('US$');
  });

  it('header/ranges/cash/debt retain their units rather than borrowing price currency', () => {
    const report = structuredClone(data.report!);
    Object.assign(report.market, { price: 4255, currency: 'GBp', market_cap: 42550000,
      market_cap_currency: 'GBP', enterprise_value: 37550000, enterprise_value_currency: 'GBP',
      cash: { value: 10000000, unit: 'GBP', period_end: '2026-09-30', provenance: 'reported' },
      total_debt: { value: 5000000, unit: 'USD', period_end: '2026-09-30', provenance: 'reported' } });
    const keyStats = { ...data.keyStats!, currency: 'GBX', range_52w: { low: 4000, high: 5000, source: 'test' } };
    view('es', { report, fair: { ...data.fair!, value: 50, currency: 'USD' }, thesis: null,
      engineRange: { low: 40, high: 60, currency: 'USD' }, keyStats });
    const header = screen.getByTestId('analyst-report').querySelector('header')!;
    expect(header.textContent).toContain('42,55');
    expect(screen.getByTestId('informe-fair').textContent).toContain('US$');
    expect(screen.getByTestId('informe-range').textContent).toContain('US$');
    expect(header.textContent).toMatch(/valor justo N\/D vs precio/);
    const market = screen.getByTestId('informe-market');
    expect(market.textContent).toContain('40,00');
    const cash = within(market).getByText('Caja').parentElement!;
    const debt = within(market).getByText('Deuda').parentElement!;
    expect(cash.textContent).toContain('GBP');
    expect(debt.textContent).toContain('US$');
  });
});
