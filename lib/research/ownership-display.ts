import type { Locale } from '@/lib/i18n/locale';
// Diccionarios del area ownership (import relativo con atributo: este módulo
// también se ejecuta en tests con node --experimental-strip-types, que no
// resuelve el alias `@/`).
import esOwnership from '../i18n/messages/es/ownership.json' with { type: 'json' };
import enOwnership from '../i18n/messages/en/ownership.json' with { type: 'json' };

/**
 * Textos revisados que el backend emite en un idioma fijo. Viven en los
 * diccionarios (ownership.backendText.*) y aquí solo se cruzan:
 * - TEXT: el backend escribe en castellano (notas de fila de
 *   investor_portfolio.py, aviso de comparación incompleta del 13F) y con
 *   inglés se traduce; un texto nuevo sale tal cual.
 * - LIMITATION: el backend publica las limitaciones del 13F como constante
 *   revisada en inglés; en UI van en español (F33). Texto desconocido: se
 *   muestra tal cual, nunca se oculta una limitación.
 */
const TEXT_KEYS = [
    'optionNotional',
    'quarterDiff',
    'codeG',
    'codeJ',
    'trumpHolder',
    'no13f',
    'comparisonIncompleteRow',
    'comparisonIncompleteRowUnits',
    'incompleteTotal',
    'no13fShort',
    'comparisonIncompleteLimitation',
] as const;
const LIMITATION_KEYS = ['limitQuarterlyLag', 'limitLongOnly', 'limitAsFiled', 'limitAmendments'] as const;

// Uso por literal para el guard de i18n (claves consumidas por iteración,
// igual que lib/knowledge-graph/graph-model.ts): sin estas cadenas el guard
// las marcaría como huérfanas nuevas.
export const OWNERSHIP_BACKEND_TEXT_KEY_LITERALS = [
    'ownership.backendText.optionNotional',
    'ownership.backendText.quarterDiff',
    'ownership.backendText.codeG',
    'ownership.backendText.codeJ',
    'ownership.backendText.trumpHolder',
    'ownership.backendText.no13f',
    'ownership.backendText.comparisonIncompleteRow',
    'ownership.backendText.comparisonIncompleteRowUnits',
    'ownership.backendText.incompleteTotal',
    'ownership.backendText.no13fShort',
    'ownership.backendText.comparisonIncompleteLimitation',
    'ownership.backendText.limitQuarterlyLag',
    'ownership.backendText.limitLongOnly',
    'ownership.backendText.limitAsFiled',
    'ownership.backendText.limitAmendments',
] as const;

const backendText = (area: typeof esOwnership, key: string): string =>
    (area.backendText as Record<string, string>)[key];

/** Nota de fila del backend (castellano) -> inglés. */
export const OWNERSHIP_TEXT_EN: Record<string, string> = Object.fromEntries(
    TEXT_KEYS.map((key) => [backendText(esOwnership, key), backendText(enOwnership, key)]),
);

/** Constante de limitación del backend (inglés) -> castellano. */
const LIMITATION_LABELS: Record<string, string> = Object.fromEntries(
    LIMITATION_KEYS.map((key) => [backendText(enOwnership, key), backendText(esOwnership, key)]),
);

/** Nota de una fila de la cartera de un inversor, en el idioma activo. */
export function ownershipNote(note: string, locale: Locale): string {
  return locale === 'en' ? OWNERSHIP_TEXT_EN[note] ?? note : note;
}

/** Traduce cada límite sin ocultar advertencias nuevas del proveedor. */
export function ownershipLimitations(value: string | string[] | null | undefined, locale: Locale = 'es', na = 'N/D'): string {
  if (!value) return '';
  const joined = Array.isArray(value) ? value.join('. ') : value;
  // En inglés el texto del backend ya es inglés (salvo el aviso de los
  // gestores sin 13F, que llega en castellano): solo se cambia el marcador.
  if (locale === 'en') return (OWNERSHIP_TEXT_EN[joined] ?? joined).replace(/\bSIN_DATOS\b/g, na);
  let text = joined.replace(/\bSIN_DATOS\b/g, na);
  for (const [original, translated] of Object.entries(LIMITATION_LABELS)) {
    text = text.replaceAll(original, translated);
  }
  return text;
}
