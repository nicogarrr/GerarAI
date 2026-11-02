import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { ttmFormulaText, ttmNoteText } from '@/lib/research/ttm-note-text';

const SPANISH = /[áéíóúñ¿¡]|\b(?:de|del|los|las|por|una|para|sin|con|su|sus|es|y|que|en|se|al|ya|lo|hay)\b/i;
const squash = (s: string) => s.replace(/"\s*\n\s*(?:f)?"/g, '');
const SERVICE = squash(readFileSync('data-engine/app/services/ttm_service.py', 'utf8'));
const FUND = squash(readFileSync('data-engine/app/services/ttm_fundamentals.py', 'utf8'));
const EPS = readFileSync('data-engine/app/services/reviewed_eps_adjustments.py', 'utf8');

const NOTE = 'BPA ajustado: transcripción revisada del PDF anual del emisor; conserva la fila ESEF original en cuarentena.';
const EPS_NOTE = 'Aproximado: el BPA no es exactamente aditivo entre trimestres (cambia el número medio de acciones).';
const NO_CHAIN = 'No hay 4 trimestres consecutivos con la misma unidad.';
const NO_PARTS = 'Faltan componentes del mismo periodo.';
const HIST = 'Dato histórico hasta 2023-12-31; no se presenta como actual: más de 18 meses respecto al último periodo disponible (2026-06-30).';
const CAPEX = 'El capex (120,00 mil M USD) supera al flujo de caja operativo (108,37 mil M USD) en el TTM: la inversión supera la caja que genera el negocio y el flujo de caja libre sale negativo.';
const OCF = 'El flujo de caja operativo ya es negativo (-2,5 M EUR) en el último trimestre; el capex lo amplía y el flujo de caja libre sale negativo.';
const FORMULA = 'Flujos: suma de los 4 últimos trimestres consecutivos (Q4 = FY − 9 meses cuando no hay 10-Q del cuarto trimestre). Balance: último trimestre. Sin 4 trimestres: último FY.';

describe('Notas TTM en inglés', () => {
  it('cada nota del backend sale en inglés, también varias seguidas', () => {
    for (const note of [NOTE, EPS_NOTE, NO_CHAIN, NO_PARTS, HIST, CAPEX, OCF, `${NOTE} ${EPS_NOTE}`, `${NO_CHAIN} ${CAPEX}`]) {
      const en = ttmNoteText(note, 'en');
      expect(en, note).not.toMatch(SPANISH);
      expect(ttmNoteText(note, 'es')).toBe(note);
    }
    expect(ttmNoteText(HIST, 'en')).toBe('Historical figure up to 2023-12-31; not shown as current: more than 18 months before the latest available period (2026-06-30).');
    expect(ttmNoteText(CAPEX, 'en')).toBe(
      'Capex (120.00B USD) exceeds operating cash flow (108.37B USD) over the TTM: investment exceeds the cash the business generates, so free cash flow is negative.',
    );
    expect(ttmNoteText(OCF, 'en')).toBe('Operating cash flow is already negative (-2.5M EUR) in the latest quarter; capex widens it and free cash flow is negative.');
    expect(ttmNoteText('El flujo de caja operativo ya es negativo (1.234 ) en el último ejercicio; el capex lo amplía y el flujo de caja libre sale negativo.', 'en'))
      .toBe('Operating cash flow is already negative (1,234) in the latest fiscal year; capex widens it and free cash flow is negative.');
    expect(ttmFormulaText(FORMULA, 'en')).not.toMatch(SPANISH);
    expect(ttmFormulaText(FORMULA, 'es')).toBe(FORMULA);
    expect(ttmNoteText('Nota nueva', 'en')).toBe('Nota nueva');
  });

  it('las frases y plantillas son las que escribe el backend', () => {
    expect(EPS).toContain(`NOTE = "${NOTE}"`);
    for (const s of [EPS_NOTE, NO_CHAIN, NO_PARTS]) expect(FUND).toContain(s);
    for (const s of [
      'Dato histórico hasta {value.period_end.isoformat()}; no se presenta como actual: más de 18 meses respecto al último periodo disponible ({latest_end.isoformat()}).',
      'El capex ({_money_es(abs(capex.value))} {unit}) supera al flujo de caja operativo ({_money_es(ocf.value)} {unit}) {window}: la inversión supera la caja que genera el negocio y el flujo de caja libre sale negativo.',
      'El flujo de caja operativo ya es negativo ({_money_es(ocf.value)} {unit}) {window}; el capex lo amplía y el flujo de caja libre sale negativo.',
      '"en el TTM"', '"en el último ejercicio"', '"en el último trimestre"', '" mil M"', 'rstrip(",") + " M"',
      FORMULA,
    ]) expect(SERVICE, s).toContain(s);
  });

  it('el panel TTM pinta las notas y la fórmula traducidas', () => {
    const panel = readFileSync('components/research/TtmPanel.tsx', 'utf8');
    expect(panel).toContain('ttmNoteText(metric.note, locale)');
    expect(panel).toContain('ttmFormulaText(ttm?.formula, locale)');
  });
});
