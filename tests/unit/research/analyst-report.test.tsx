import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';

import { AnalystReportView } from '@/components/research/AnalystReportView';
import { createFormatters } from '@/lib/format';
import { createTranslator } from '@/lib/i18n/translate';
import { engineRangeFrom, fairValueRange, thesisRisks, userEstimates, vsPrice, reportVsPrice, type ReportInputs } from '@/lib/research/analyst-report';
import type { SotpResponse } from '@/lib/research/sotp';
import type { BaseRateCheck } from '@/lib/research/valuation-summary';
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

describe('consenso propio en el informe', () => {
  const consensus = {
    version: 'consenso_propio v1',
    cells: [
      { metric: 'revenue', period: 'fy2027', period_end: '2027-09-30', status: 'estimado', source: 'modelo', low: 1, mid: 400_000_000_000, high: 2, formula: 'año anterior × (1 + g)', citations: [{ kind: 'dato_presentado', url: 'https://www.sec.gov/Archives/edgar/data/320193/x.htm' }] },
      { metric: 'operating_income', period: 'fy2027', period_end: '2027-09-30', status: 'estimado', source: 'guia', mid: 170_000_000_000, citations: [] },
      { metric: 'eps', period: 'fy2027', period_end: '2027-09-30', status: 'estimado', source: 'modelo', mid: 9.634, formula: 'BPA fy2026 presentado 8,98 × …', citations: [] },
      { metric: 'eps', period: 'q4_2027', period_end: '2027-09-30', status: 'sin_estimacion', source: null, mid: null, reason: 'ninguna fuente disponible pasa las puertas' },
      { metric: 'revenue', period: 'q1_2026', period_end: '2025-12-31', status: 'vencido', mid: null },
      { metric: 'revenue', period: 'q1_2027', period_end: '2026-12-31', status: 'estimado', source: 'tasa_base', mid: 150_000_000_000, citations: [] },
    ],
  };

  it('agrupa por periodo en orden, sin vencidos ni periodos sin ninguna estimación', async () => {
    const { consensusRows, consensusSourceUrl } = await import('@/lib/research/analyst-report');
    const rows = consensusRows(consensus);
    expect(rows.map((r) => r.period)).toEqual(['q1_2027', 'fy2027']);
    expect(rows[1].cells.eps?.mid).toBeCloseTo(9.634);
    expect(consensusSourceUrl(rows[1].cells.revenue)).toBe('https://www.sec.gov/Archives/edgar/data/320193/x.htm');
    expect(consensusSourceUrl(rows[1].cells.eps)).toBeNull();
    expect(consensusRows(null)).toEqual([]);
  });

  it('pinta ingresos, beneficio operativo y BPA con su fuente y enlace; N/D sin consenso', () => {
    view('es', { consensus });
    const table = screen.getByRole('region', { name: /Consenso propio de GerarAI/ });
    const fy = within(table).getByRole('row', { name: /Ej\./ });
    expect(fy.textContent).toContain('9,63');
    expect(fy.textContent).toContain('modelo propio');
    expect(fy.textContent).toContain('guía de la empresa');
    const link = within(fy).getByRole('link', { name: 'modelo propio' });
    expect(link.getAttribute('href')).toBe('https://www.sec.gov/Archives/edgar/data/320193/x.htm');
    expect(within(table).getByText('tasa base SEC')).toBeTruthy();
    view('en', { consensus: null });
    expect(screen.getAllByTestId('informe-consensus').at(-1)?.textContent).toContain('no own estimate');
  });
});

describe('tasa base: con qué frecuencia lo consiguieron', () => {
  const cell = (check: BaseRateCheck | null) => ({ version: 'v', cells: [
    { metric: 'revenue', period: 'fy2027', period_end: '2027-12-31', status: 'estimado', source: 'modelo', mid: 512_000_000, formula: 'f', citations: [], base_rate_check: check },
  ] });

  it('la celda de ingresos dice qué % de comparables lo logró, con la fórmula al pasar el ratón', () => {
    const formula = 'crecimiento implícito (fy2027 estimado 512 / fy2026 estimado 253) − 1 = +102,1 %; el 6% …';
    view('es', { consensus: cell({ share: 0.065, bound: '=', formula, n: 63 }) });
    const reach = screen.getByTestId('consensus-base-rate-reach');
    expect(reach.textContent).toMatch(/Lo logró el 7\s?% de comparables en 1 año/);
    expect(reach.getAttribute('title')).toBe(formula);
  });

  it('fuera de la rejilla dice «menos del»; sin cifra (N/D con motivo) no pinta nada', () => {
    view('en', { consensus: cell({ share: 0.05, bound: '<', formula: 'x' }) });
    expect(screen.getByTestId('consensus-base-rate-reach').textContent).toMatch(/Reached by under 5\s?% of peers/);
    view('es', { consensus: cell({ share: null, reason: 'ejercicio en curso' }) });
    expect(screen.getAllByTestId('consensus-base-rate-reach')).toHaveLength(1);
  });
});

describe('cifras reales con enlace al filing', () => {
  it('la cifra real enlaza al filing cuando el informe trae su URL', () => {
    const report = (data.report ? JSON.parse(JSON.stringify(data.report)) : null) as ReportInputs['report'];
    const row = report?.estimates.annual.at(-1);
    if (!report || !row?.revenue) throw new Error('fixture sin ingresos anuales');
    row.revenue.url = 'https://www.sec.gov/Archives/edgar/data/1780312/000178031226000010/0001780312-26-000010-index.htm';
    view('es', { report });
    const annual = screen.getByRole('region', { name: /Por ejercicio/ });
    const links = within(annual).getAllByRole('link');
    expect(links.some((a) => a.getAttribute('href') === row.revenue?.url)).toBe(true);
  });
});

describe('capitalización de un ADR', () => {
  it('con ratio de ADR la nota explica la conversión de acciones ordinarias', () => {
    const report = data.report!;
    view('es', { report: { ...report, market: { ...report.market, market_cap_basis: 'shares_outstanding', market_cap_adr_ratio: 5 } } });
    const market = screen.getByTestId('informe-market');
    expect(market.textContent).toContain('1 ADR = 5 acciones ordinarias');
    expect(market.textContent).not.toContain('Con acciones diluidas');
  });
});

describe('EBITDA derivado de emisores IFRS', () => {
  it('sin resultado operativo etiquetado, el EBITDA por componentes lleva ³ y su nota', () => {
    const report = (data.report ? JSON.parse(JSON.stringify(data.report)) : null) as ReportInputs['report'];
    const row = report?.estimates.annual.at(-1);
    if (!report || !row) throw new Error('fixture sin ejercicios');
    row.ebitda = { value: 23459e6, unit: 'USD', source: 'SEC', reported: false, basis: 'pretax_less_net_finance_result_plus_da', derived_q4: false, url: null };
    view('es', { report });
    const annual = screen.getByRole('region', { name: /Por ejercicio/ });
    expect(annual.textContent).toContain('³');
    expect(document.body.textContent).toContain('beneficio antes de impuestos − resultado financiero neto + amortizaciones');
  });
});
