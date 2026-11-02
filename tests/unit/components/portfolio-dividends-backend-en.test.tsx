import { readFileSync } from 'node:fs';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('@/components/portfolio/SyncDividendsButton', () => ({ default: () => null }));
import PortfolioDividends from '@/components/portfolio/PortfolioDividends';
import { createFormatters } from '@/lib/format';
import { createTranslator } from '@/lib/i18n/translate';
import { dividendProjectionText } from '@/lib/portfolio-dividends-text';

// Textos en castellano que manda dividend_projection_service.py (supuestos
// fiscales, notas de cada año, motivos de retención sin verificar, condiciones
// del escenario y la nota de los declarados). Si cambian allí, este test avisa
// de que la tabla en inglés se ha quedado atrás.
const SOURCE = readFileSync('data-engine/app/services/dividend_projection_service.py', 'utf8').replace(/"\s*\n\s*f?"/g, '');
const block = (name: string) => SOURCE.slice(SOURCE.indexOf(`${name} = [`), SOURCE.indexOf(']', SOURCE.indexOf(`${name} = [`)));
const CONDITIONS = [...block('_FISCAL_CONDITIONS').matchAll(/"([^"]+)"/g)].map((m) => m[1]);
const TEXTS = [
  'Declarado con ex_date futura según el proveedor de datos (no verificado contra fuente primaria); no alimenta la réplica.',
  'Sin datos',
  'Sin datos: todas las posiciones con dividendo proyectado este año carecen de tipo de cambio o de retención verificada (N/D, no cero).',
  'Escenario fiscal no disponible: la divisa base no es EUR.',
  'Escenario condicionado (ver «Supuestos fiscales y fuentes»); no es el neto final.',
  'Subconjunto cubierto: hay posiciones excluidas sin tipo de cambio o sin retención verificada (sin datos, no cero). ',
  'Emisor constituido en Islas Caimán (ADS en NYSE; la sede en Hong Kong es la que figura como domicilio en la base de datos). Sin tipo de retención verificado.',
  'Sin domicilio ni emisor verificado; retención no verificada.',
  'Escenario 0 % = solo ley de Islas Caimán (20-F Item 10.E): sin retención en Caimán. Condiciones: Alibaba no cree ser residente fiscal en China, pero si las autoridades chinas la trataran como tal podría aplicarse 20 % de IIT a un tenedor persona física no residente, con reducción por convenio incierta para ADS. Comisiones del depositario aparte. Retención efectiva del broker: NO verificada.',
];
const TEMPLATES = [
  'Emisor en {country} sin tipo de retención verificado.',
  'Domicilio en base de datos: {country}; sin tipo de retención verificado para ese país (no se deduce del mercado ni se asume 0 %).',
];
const SPANISH = /[áéíóúñ]|\b(sin|del|para|datos|retención|posiciones|escenario|emisor|supuestos)\b/i;
const en = createFormatters('en');
const ti = createTranslator('en');

beforeAll(() => {
  window.matchMedia ??= ((query: string) => ({ matches: false, media: query, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false })) as unknown as typeof window.matchMedia;
});

describe('dividend projection: backend texts in English', () => {
  it('the backend still sends these texts and each has an English version', () => {
    expect(CONDITIONS).toHaveLength(11);
    for (const text of [...TEXTS, ...CONDITIONS]) {
      expect(SOURCE, text).toContain(text);
      expect(dividendProjectionText(text, 'en'), text).not.toMatch(SPANISH);
      expect(dividendProjectionText(text, 'es')).toBe(text);
    }
    for (const template of TEMPLATES) {
      expect(SOURCE, template).toContain(template);
      const text = template.replace('{country}', 'GB');
      expect(dividendProjectionText(text, 'en'), text).not.toMatch(SPANISH);
      expect(dividendProjectionText(text, 'en')).toContain('GB');
    }
    const subset = TEXTS[5] + TEXTS[4];
    expect(SOURCE).toContain('"Subconjunto cubierto: hay posiciones excluidas sin tipo de cambio o sin retención verificada (sin datos, no cero). " + note');
    expect(dividendProjectionText(subset, 'en')).not.toMatch(SPANISH);
    expect(dividendProjectionText('IRPF real', 'en')).toBe('IRPF real');
    expect(dividendProjectionText(null, 'en')).toBeNull();
    expect(dividendProjectionText(CONDITIONS[4], 'en')).toContain('IRPF (Spanish income tax)');
  });

  it('the dividends tab shows the backend texts in English', () => {
    const projection = {
      as_of: '2026-10-01', base_currency: 'EUR', horizon_months: 12, label: 'x', method: 'm',
      fiscal_conditions: CONDITIONS, sources: {}, months: [],
      fiscal_by_year: { 2026: { gross_base: 90, irpf_scenario: 17, source_withheld_foreign: 13.5, retencion_a_cuenta_es: 0, double_tax_deduction: 13.5,
        cuota_pendiente_estimada: 3.5, net_scenario: 73, effective_avg_rate: 0.19, covered_tickers: ['KO'], excluded_tickers: ['VOD'], note: TEXTS[5] + TEXTS[4] } },
      positions: [
        { ticker: 'KO', currency: 'USD', quantity: 10, frequency_last_year: 4, gross_native: 100, gross_base: 90, domicile_country: 'US', source_withholding_rate: 0.15, source_withheld_base: 13.5, months: {} },
        { ticker: 'BABA', currency: 'USD', quantity: 5, frequency_last_year: 1, gross_native: 10, gross_base: 9, domicile_country: 'KY', source_withholding_rate: 0, source_withheld_base: 0, months: {}, withholding_kind: 'sin_impuesto_origen_escenario', scenario_conditions: TEXTS[8] },
        { ticker: 'VOD', currency: 'GBP', quantity: 5, frequency_last_year: 2, gross_native: 10, gross_base: 11, domicile_country: 'GB', source_withholding_rate: null, source_withheld_base: null, months: {}, unverified_reason: TEMPLATES[1].replace('{country}', 'GB') },
      ],
      declared_future: [{ ticker: 'KO', ex_date: '2026-11-14', pay_date: null, amount_per_share: 0.51, currency: 'USD', label: 'INGESTADO', source: 'fmp', projection_as_of: '2026-10-01', note: TEXTS[0] }],
      coverage: { with_data: 2, sin_datos: [], fx_missing: [], unknown_source_withholding: ['VOD'], unverified_reasons: { VOD: TEMPLATES[1].replace('{country}', 'GB') } },
    };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { container } = render(<PortfolioDividends projection={projection as any} ti={ti} f={en} />);
    expect(screen.getByText('Spanish tax residence assumed.')).toBeTruthy();
    expect(screen.getAllByText(/^Database domicile: GB; no verified withholding rate/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/^0% scenario = Cayman Islands law only/).length).toBeGreaterThan(0);
    expect(container.textContent).toContain('INGESTED · fmp');
    expect(container.textContent).toContain('Declared with a future ex-date');
    expect(container.textContent).toContain('Covered subset:');
    const text = container.textContent ?? '';
    for (const spanish of ['Residencia fiscal', 'Domicilio en base', 'Escenario 0 %', 'INGESTADO', 'Declarado con', 'Subconjunto cubierto', 'Escenario condicionado']) {
      expect(text, spanish).not.toContain(spanish);
    }
  });

  it('in Spanish the backend texts are shown as sent', () => {
    expect(dividendProjectionText(TEXTS[0], 'es')).toBe(TEXTS[0]);
    expect(dividendProjectionText('INGESTADO', 'es')).toBe('INGESTADO');
  });
});
