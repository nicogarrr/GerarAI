import { describe, expect, it } from 'vitest';

import {
  baseAssumptionsText,
  blockerLabel,
  reverseDcfText,
  scenarioNotesList,
  waccSourceLabel,
} from '@/lib/research/valuation-display';

describe('blockerLabel', () => {
  it('explica traceable_wacc como falta (no como presencia)', () => {
    expect(blockerLabel('traceable_wacc')).toBe('WACC sin cálculo trazable');
    expect(blockerLabel('traceable_wacc', 'en')).toBe('WACC without a traceable calculation');
    expect(blockerLabel('forecast_is_not_the_driver', 'en')).not.toBe(blockerLabel('forecast_is_not_the_driver'));
    expect(blockerLabel('otro_motivo', 'en')).toBe('otro_motivo');
    expect(blockerLabel('traceable_wacc')).not.toContain('por defecto');
  });
  it('mantiene ids desconocidos tal cual', () => {
    expect(blockerLabel('otro_motivo')).toBe('otro_motivo');
  });
});

describe('waccSourceLabel', () => {
  it('traduce las fuentes conocidas', () => {
    expect(waccSourceLabel('calculated_metric')).toContain('trazables');
    expect(waccSourceLabel('tag_default')).toContain('sin fuente trazable');
    expect(waccSourceLabel('inferred_input')).toContain('inferido');
  });
  it('null sin fuente', () => {
    expect(waccSourceLabel(null)).toBeNull();
    expect(waccSourceLabel(undefined)).toBeNull();
  });
});

describe('reverseDcfText', () => {
  it('ok: crecimiento exigido con base (margen y WACC)', () => {
    const text = reverseDcfText({ status: 'ok', required_revenue_growth: 0.0921, fcf_margin: 0.0107, wacc: 0.09 });
    expect(text).toContain('9,21');
    expect(text).toContain('1,07');
    expect(text).toContain('no es una previsión');
  });
  it('out_of_bounds explicado, sin cifra de crecimiento', () => {
    const text = reverseDcfText({ status: 'out_of_bounds', out_of_bounds: true });
    expect(text).toContain('fuera de rango');
    expect(text).toContain('−25 %');
    expect(text).not.toContain('exige un crecimiento de ingresos del');
  });
  it('not_applicable explicado', () => {
    expect(reverseDcfText({ status: 'not_applicable' })).toContain('no aplicable');
  });
  it('null sin estado ni crecimiento', () => {
    expect(reverseDcfText({})).toBeNull();
    expect(reverseDcfText(null)).toBeNull();
  });
});

describe('baseAssumptionsText', () => {
  const trace = {
    scenarios: { base: { definition: { assumptions: { fcf_margin: 0.0107, revenue_growth: 0.07 } } } },
    periods: { fcf_margin: 'FY2025' },
    wacc: 0.09,
    wacc_source: 'tag_default',
  };
  it('resume margen con periodo, crecimiento y WACC con fuente', () => {
    const text = baseAssumptionsText(trace);
    expect(text).toContain('margen FCF 1,07');
    expect(text).toContain('FY2025');
    expect(text).toContain('crecimiento de ingresos 7');
    expect(text).toContain('WACC 9');
    expect(text).toContain('sin fuente trazable');
  });
  it('null con traza vacía', () => {
    expect(baseAssumptionsText({})).toBeNull();
    expect(baseAssumptionsText(null)).toBeNull();
  });
});

describe('scenarioNotesList', () => {
  it('ordena bear/base/bull/expected y omite vacías', () => {
    expect(scenarioNotesList({ expected: 'e', base: '', bear: 'b' })).toEqual(['b', 'e']);
  });
  it('lista vacía sin notas', () => {
    expect(scenarioNotesList(null)).toEqual([]);
    expect(scenarioNotesList({})).toEqual([]);
  });
});
