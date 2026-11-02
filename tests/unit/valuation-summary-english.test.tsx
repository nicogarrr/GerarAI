import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { ValuationSummaryCard } from '@/components/research/ValuationSummaryGrid';
import { LocaleProvider } from '@/lib/i18n/client';
import { healthMissingLabel, valuationSummaryText, piotroskiSignalText, type ValuationSummary } from '@/lib/research/valuation-summary';

// Textos tal cual los mandan financial_health.py, fair_value_service.py y valuation_summary.py.
const SIGNALS: Array<[string, string, string]> = [
  ['roa', 'Beneficio sobre activos positivo', 'Beneficio neto(t) / Activos(t-1) > 0'],
  ['cfo', 'Flujo operativo positivo', 'Flujo operativo(t) / Activos(t-1) > 0'],
  ['delta_roa', 'Rentabilidad sobre activos mejora', 'ROA(t) > ROA(t-1)  (ROA = Beneficio neto / Activos del año anterior)'],
  ['accrual', 'Caja operativa superior al beneficio', 'Flujo operativo(t) / Activos(t-1) > ROA(t)'],
  ['leverage', 'Apalancamiento a largo plazo baja', 'Deuda a largo plazo(t) / Activos medios(t) < Deuda a largo plazo(t-1) / Activos medios(t-1)'],
  ['liquidity', 'Liquidez corriente mejora', 'Activo corriente(t) / Pasivo corriente(t) > Activo corriente(t-1) / Pasivo corriente(t-1)'],
  ['issuance', 'Sin emisión de capital común', 'Emisión de acciones ordinarias(t) = 0 (dato explícito)'],
  ['margin', 'Margen bruto mejora', 'Beneficio bruto(t) / Ventas(t) > Beneficio bruto(t-1) / Ventas(t-1)'],
  ['turnover', 'Rotación de activos mejora', 'Ventas(t) / Activos(t-1) > Ventas(t-1) / Activos(t-2)'],
];
const FIXED = [
  'Sector sin clasificar',
  'Modelo no aplicable a financieras, REIT o empresas preingresos',
  'Sin ejercicios anuales con fuente',
  'Ejercicio desactualizado o fechas incoherentes',
  'Faltan puntos verificables; no se publica un F-score parcial',
  'Indicadores contables, no recomendación ni probabilidad de quiebra.',
  'Modelo fundamental persistido',
  'Sin valor justo',
  'Motor de valoración',
  'Motor de valoración (orientativo)',
];

const item: ValuationSummary = {
  ticker: 'DEMO', fair_value: { value: 100, currency: 'USD', label: 'Tesis publicada v3 (antigua)', as_of: '2026-10-29', publishable: true, stale: false },
  reverse_dcf: { status: 'ok', required_revenue_growth: .08, as_of: '2026-10-29', source: 'Modelo fundamental persistido', market_price: 80, model_version_id: 1 },
  health: { status: 'not_evaluable', reason: 'Faltan puntos verificables; no se publica un F-score parcial',
    notice: 'Indicadores contables, no recomendación ni probabilidad de quiebra.',
    piotroski: { score: null, evaluated: 1, total: 9, methodology_url: 'https://example.com/p', signals: [
      { id: 'roa', label: SIGNALS[0][1], formula: SIGNALS[0][2], point: 1, missing_input: null, evidence: [] },
      { id: 'cfo', label: SIGNALS[1][1], formula: SIGNALS[1][2], point: null, missing_input: 'denominador no positivo', evidence: [] },
      { id: 'margin', label: SIGNALS[7][1], formula: SIGNALS[7][2], point: null, missing_input: 'gross_profit:FY2024', evidence: [] },
    ] },
    altman: { score: null, status: 'not_evaluable', variant: 'Z_double_prime', reason: 'divisas no comparables', methodology_url: 'https://example.com/a' } },
};

describe('valuation summary in English', () => {
  it('every fixed backend text has an English version and stays as is in Spanish', () => {
    for (const text of FIXED) {
      expect(valuationSummaryText(text, 'en'), text).not.toBe(text);
      expect(valuationSummaryText(text, 'es')).toBe(text);
    }
    expect(valuationSummaryText('Tesis publicada v3 (antigua)', 'en')).toBe('Published thesis v3 (old)');
    expect(valuationSummaryText('Tesis publicada v12', 'en')).toBe('Published thesis v12');
    expect(valuationSummaryText('Texto nuevo', 'en')).toBe('Texto nuevo');
  });

  it('every Piotroski signal has an English label and formula', () => {
    for (const [id, label, formula] of SIGNALS) {
      const en = piotroskiSignalText({ id, label, formula }, 'en');
      expect(en.label, id).not.toBe(label);
      expect(en.formula, id).not.toBe(formula);
      expect(piotroskiSignalText({ id, label, formula }, 'es')).toEqual({ label, formula });
    }
    expect(piotroskiSignalText({ id: 'nuevo', label: 'L', formula: 'F' }, 'en')).toEqual({ label: 'L', formula: 'F' });
  });

  it('missing inputs read in English', () => {
    expect(healthMissingLabel('denominador no positivo', 'en')).toBe('non-positive denominator');
    expect(healthMissingLabel('periodos no comparables', 'en')).toBe('periods not comparable');
    expect(healthMissingLabel('divisas no comparables', 'en')).toBe('currencies not comparable');
    expect(healthMissingLabel('gross_profit:FY2024', 'en')).toMatch(/\(FY 2024\)$/);
    expect(healthMissingLabel('gross_profit:FY2024')).toMatch(/\(ejercicio 2024\)$/);
  });

  it('the card shows no Spanish backend text in English mode', () => {
    render(<LocaleProvider locale="en"><ValuationSummaryCard item={item} quote={{ symbol: 'DEMO', price: 80, currency: 'USD' }} /></LocaleProvider>);
    expect(screen.getByText(/Published thesis v3 \(old\)/)).toBeInTheDocument();
    expect(screen.getByText(/Return on assets is positive/)).toBeInTheDocument();
    expect(screen.queryByText(/Beneficio|Flujo operativo|Margen bruto|Faltan puntos|Indicadores contables|Modelo fundamental|Tesis publicada|denominador|divisas|ejercicio/)).not.toBeInTheDocument();
  });
});
