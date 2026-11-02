import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { baseAssumptionsText, reverseDcfText, waccSourceLabel } from '@/lib/research/valuation-display';

// Ficha → Valoración con el idioma en inglés: el DCF inverso y los supuestos
// del escenario base se escribían siempre en castellano.
const SPANISH = /\b(precio|crecimiento|exige|anual|margen|supuestos|escenario|periodo|previsión|fuera de rango|no aplicable|calculado|inferido|por defecto|sin fuente)\b/i;

describe('valuation-display en inglés', () => {
  it('DCF inverso ok: frase y cifras en inglés', () => {
    const text = reverseDcfText({ status: 'ok', required_revenue_growth: 0.0921, fcf_margin: 0.0107, wacc: 0.09 }, 'en');
    expect(text).toBe('The model price requires annual revenue growth of 9.21% (with an FCF margin of 1.07% and a WACC of 9.00%); it is not a forecast, it is what the price already discounts.');
  });

  it('DCF inverso fuera de rango y no aplicable en inglés', () => {
    const out = reverseDcfText({ status: 'out_of_bounds', out_of_bounds: true }, 'en');
    const na = reverseDcfText({ status: 'not_applicable' }, 'en');
    expect(out).toContain('Reverse DCF out of range');
    expect(na).toContain('Reverse DCF not applicable');
    expect(out).not.toMatch(SPANISH);
    expect(na).not.toMatch(SPANISH);
  });

  it('supuestos del escenario base en inglés, con la fuente del WACC', () => {
    const trace = {
      scenarios: { base: { definition: { assumptions: { fcf_margin: 0.0107, revenue_growth: 0.07 } } } },
      periods: { fcf_margin: 'FY2025' },
      wacc: 0.09,
      wacc_source: 'tag_default',
    };
    expect(baseAssumptionsText(trace, 'en')).toBe(
      "Base scenario assumptions: FCF margin 1.07% (period FY2025) · revenue growth 7.00% · WACC 9.00% (the model's default rate, without a traceable source).",
    );
  });

  it('las tres fuentes del WACC tienen texto en inglés; una desconocida pasa tal cual', () => {
    for (const source of ['calculated_metric', 'inferred_input', 'tag_default']) {
      const text = waccSourceLabel(source, 'en');
      expect(text).not.toBe(source);
      expect(text).not.toMatch(SPANISH);
    }
    expect(waccSourceLabel('otra_fuente', 'en')).toBe('otra_fuente');
  });

  it('sin idioma sigue en castellano (por defecto)', () => {
    expect(reverseDcfText({ status: 'not_applicable' })).toContain('DCF inverso no aplicable');
    expect(baseAssumptionsText({ wacc: 0.09, wacc_source: 'inferred_input' })?.replace(/\u00a0/g, ' ')).toBe('Supuestos del escenario base: WACC 9,00 % (inferido, con fuentes).');
  });

  it('la ficha pasa el idioma a las dos frases', () => {
    const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
    expect(page).toContain('reverseDcfText(valuation.reverse_dcf, locale)');
    expect(page).toContain('baseAssumptionsText(valuation.trace, locale)');
  });
});
