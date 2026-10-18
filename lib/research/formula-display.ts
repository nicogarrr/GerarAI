// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { METRIC_LABELS } from './metric-labels.ts';

const FUNCTION_NAMES: Record<string, string> = {
  average: 'media', avg: 'media', sum: 'suma', max: 'máx.', min: 'mín.', abs: 'abs.', median: 'mediana',
};

/** Fórmula del backend («operating_income * (1 - effective_tax_rate) / average(...)») en castellano:
 *  identificadores con la etiqueta de la métrica y operadores con signos de lectura.
 *  Solo cambia la presentación; el código original se conserva aparte. */
const PHRASES: Array<[RegExp, string]> = [
  [/,?\s*using current invested capital when no coherent prior period exists/g, '; usa el capital invertido actual si no hay un periodo previo coherente'],
  [/,?\s*where\s+/g, '; donde '],
  [/\badjusted invested capital\b/g, 'capital invertido ajustado'],
];

export function formulaDisplay(formula: string | null | undefined): string {
  if (!formula) return '';
  const translated = formula
    .replace(/\b[a-z][a-z0-9]*(?:_[a-z0-9]+)*\b/g, (token) =>
      FUNCTION_NAMES[token] ?? METRIC_LABELS[token] ?? token.replaceAll('_', ' '))
    .replaceAll(' * ', ' × ')
    .replaceAll(' / ', ' ÷ ');
  return PHRASES.reduce((text, [pattern, value]) => text.replace(pattern, value), translated);
}
