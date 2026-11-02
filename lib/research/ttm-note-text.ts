/**
 * Notas de los fundamentales TTM (ttm_service.py, ttm_fundamentals.py y
 * reviewed_eps_adjustments.py): el backend las compone en castellano por
 * petición (no se guardan), a veces varias seguidas en la misma nota y con
 * importes en formato es-ES («11,63 mil M»). En inglés se traduce cada frase
 * reconocida y los importes pasan a formato inglés («11.63B»); en castellano,
 * y con una frase que no se reconoce, queda el texto del backend tal cual.
 */
import type { Locale } from '@/lib/i18n/locale';

const FIXED_EN: Array<[string, string]> = [
  [
    'BPA ajustado: transcripción revisada del PDF anual del emisor; conserva la fila ESEF original en cuarentena.',
    "Adjusted EPS: reviewed transcription of the issuer's annual PDF; the original ESEF row is kept in quarantine.",
  ],
  [
    'Aproximado: el BPA no es exactamente aditivo entre trimestres (cambia el número medio de acciones).',
    'Approximate: EPS is not exactly additive across quarters (the average share count changes).',
  ],
  ['No hay 4 trimestres consecutivos con la misma unidad.', 'There are no 4 consecutive quarters in the same unit.'],
  ['Faltan componentes del mismo periodo.', 'Components from the same period are missing.'],
];

const FORMULA_ES =
  'Flujos: suma de los 4 últimos trimestres consecutivos (Q4 = FY − 9 meses cuando no hay 10-Q del cuarto trimestre). Balance: último trimestre. Sin 4 trimestres: último FY.';
const FORMULA_EN =
  'Flows: sum of the last 4 consecutive quarters (Q4 = FY − 9 months when there is no fourth-quarter 10-Q). Balance sheet: latest quarter. Without 4 quarters: latest FY.';

const WINDOW_EN: Record<string, string> = {
  'en el TTM': 'over the TTM',
  'en el último ejercicio': 'in the latest fiscal year',
  'en el último trimestre': 'in the latest quarter',
};
const WINDOW = '(en el TTM|en el último ejercicio|en el último trimestre)';
const AMOUNT = '(-?[\\d.,]+(?: mil M| M)?)( [A-Z]{3}(?:/[a-z]+)?| )?';

/** «11,63 mil M» → «11.63B», «35,7 M» → «35.7M», «1.234» → «1,234». */
function amountEn(amount: string, unit = ''): string {
  let text: string;
  if (amount.endsWith(' mil M')) text = `${amount.slice(0, -6).replace(',', '.')}B`;
  else if (amount.endsWith(' M')) text = `${amount.slice(0, -2).replace(',', '.')}M`;
  else text = amount.replaceAll('.', ',');
  return text + unit.trimEnd();
}

const PATTERNS_EN: Array<[RegExp, (...groups: string[]) => string]> = [
  [
    /Dato histórico hasta (\d{4}-\d{2}-\d{2}); no se presenta como actual: más de 18 meses respecto al último periodo disponible \((\d{4}-\d{2}-\d{2})\)\./g,
    (until, latest) => `Historical figure up to ${until}; not shown as current: more than 18 months before the latest available period (${latest}).`,
  ],
  [
    new RegExp(
      `El capex \\(${AMOUNT}\\) supera al flujo de caja operativo \\(${AMOUNT}\\) ${WINDOW}: la inversión supera la caja que genera el negocio y el flujo de caja libre sale negativo\\.`,
      'g',
    ),
    (capex, capexUnit, ocf, ocfUnit, window) =>
      `Capex (${amountEn(capex, capexUnit)}) exceeds operating cash flow (${amountEn(ocf, ocfUnit)}) ${WINDOW_EN[window]}: investment exceeds the cash the business generates, so free cash flow is negative.`,
  ],
  [
    new RegExp(`El flujo de caja operativo ya es negativo \\(${AMOUNT}\\) ${WINDOW}; el capex lo amplía y el flujo de caja libre sale negativo\\.`, 'g'),
    (ocf, ocfUnit, window) => `Operating cash flow is already negative (${amountEn(ocf, ocfUnit)}) ${WINDOW_EN[window]}; capex widens it and free cash flow is negative.`,
  ],
];

export function ttmNoteText<T extends string | null | undefined>(note: T, locale: Locale): T | string {
  if (locale !== 'en' || !note) return note;
  let text: string = note;
  for (const [es, en] of FIXED_EN) text = text.split(es).join(en);
  for (const [pattern, render] of PATTERNS_EN) {
    text = text.replace(pattern, (_match: string, ...groups: unknown[]) =>
      render(...groups.slice(0, render.length).map((g) => (typeof g === 'string' ? g : ''))),
    );
  }
  return text;
}

export function ttmFormulaText<T extends string | null | undefined>(formula: T, locale: Locale): T | string {
  if (locale !== 'en' || !formula) return formula;
  return formula === FORMULA_ES ? FORMULA_EN : formula;
}
