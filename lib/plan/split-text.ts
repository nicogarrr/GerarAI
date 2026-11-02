/**
 * Reparto de la aportación (plan_contribution_split.py) en el idioma de la
 * interfaz. El backend compone en castellano el resumen, las notas y el
 * motivo de cada fila; en inglés se rehacen con los campos estructurados de
 * la respuesta (nivel, caducidad, multiplicador, importes). En castellano, y
 * con un texto que no se reconoce, pasa el del backend tal cual.
 */
import type { Locale } from '@/lib/i18n/locale';
import type { ContributionAllocation, ContributionSplit } from '@/lib/plan/contribution-split';

const LEVEL_LABELS_EN: Record<number, string> = {
  4: '4X DCA', 3: '3X DCA', 2: '2X DCA', 1: '1X DCA', [-1]: 'LIGHT TRIM', [-2]: 'HEAVY TRIM',
};

export function splitReasonText(row: ContributionAllocation, locale: Locale): string {
  if (locale !== 'en') return row.reason;
  if (row.dca_stale) return `stale DCA level (month ${row.dca_period || 'n/a'}): normal weight (1X) until re-evaluated`;
  if (row.dca_level === null || row.dca_level === undefined) return 'no DCA level: normal weight (1X)';
  const label = LEVEL_LABELS_EN[row.dca_level] ?? `level ${row.dca_level}`;
  if (row.multiplier === 0) return `${label}: trim zone, no contribution this month`;
  return `${label}: weight ×${row.multiplier}`;
}

const NOTES_EN: Record<string, string> = {
  'El plan no tiene objetivos por ticker: se reparte a partes iguales entre las posiciones vivas.':
    'The plan has no per-ticker targets: the contribution is split equally across open positions.',
  'El motor DCA no está desplegado todavía: el reparto sigue solo los pesos del plan (todos como 1X).':
    'The DCA engine is not deployed yet: the split follows only the plan weights (all as 1X).',
  'Ningún ticker del plan tiene nivel DCA calculado: todos pesan como 1X.': 'No ticker in the plan has a computed DCA level: all weigh as 1X.',
  'La divisa de la aportación no está registrada en el plan.': 'The contribution currency is not recorded in the plan.',
};

const STALE_NOTE = /^Nivel DCA de hace más de un mes en (.+): pesa como 1X hasta que se vuelva a evaluar\.$/;

export function splitNoteText(note: string, locale: Locale): string {
  if (locale !== 'en') return note;
  if (Object.hasOwn(NOTES_EN, note)) return NOTES_EN[note];
  const stale = STALE_NOTE.exec(note);
  return stale ? `DCA level older than a month for ${stale[1]}: weighted as 1X until re-evaluated.` : note;
}

/** Resumen «Este mes X a POOL, …»; `money` formatea importe + divisa en el idioma activo. */
export function splitSummaryText(split: ContributionSplit, locale: Locale, money: (value: number) => string): string | null | undefined {
  if (locale !== 'en' || !split.summary) return split.summary;
  if (split.status === 'ok') {
    const funded = (split.allocations ?? []).filter((row) => row.amount > 0);
    if (funded.length) return `This month ${funded.map((row) => `${money(row.amount)} to ${row.ticker}`).join(', ')}`;
  }
  if (split.status === 'all_trim' && typeof split.amount === 'number') {
    return `This month the whole plan is in the trim zone: the ${money(split.amount)} stay in cash.`;
  }
  return split.summary;
}
