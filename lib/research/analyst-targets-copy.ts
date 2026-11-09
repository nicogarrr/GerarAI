/**
 * Textos del panel de analistas a partir de los CÓDIGOS del backend.
 *
 * El backend manda las notas y la fuente del precio de referencia en
 * castellano (`note`, `reference_price_source`) y, desde este cambio, también
 * un código estable (`note_code`, `reference_price_source_code`). Con la app
 * en inglés el panel pintaba el castellano tal cual («fuente de mercado,
 * precio al obtener los datos»); ahora traduce por código con los
 * diccionarios es/en. Sin código (backend antiguo) se conserva el texto.
 */
import type { TranslateFn } from '../i18n/translate.ts';

export type AnalystTargetsCopyInput = {
  symbol: string;
  note?: string | null;
  note_code?: 'fetch_failed' | 'not_equity' | 'consensus_only' | 'no_targets' | 'with_press' | null;
  instrument_type?: string | null;
  reference_price_source?: string | null;
  reference_price_source_code?: 'market_at_fetch' | null;
};

function instrumentText(type: string | null | undefined, t: TranslateFn): string {
  const normalized = (type ?? '').trim().toUpperCase();
  switch (normalized) {
    case '': return t('ui.analystTargets.instrument.unknown');
    case 'ETF': return t('ui.analystTargets.instrument.ETF');
    case 'MUTUALFUND': return t('ui.analystTargets.instrument.MUTUALFUND');
    case 'INDEX': return t('ui.analystTargets.instrument.INDEX');
    case 'CURRENCY': return t('ui.analystTargets.instrument.CURRENCY');
    case 'CRYPTOCURRENCY': return t('ui.analystTargets.instrument.CRYPTOCURRENCY');
    case 'FUTURE': return t('ui.analystTargets.instrument.FUTURE');
    case 'OPTION': return t('ui.analystTargets.instrument.OPTION');
    default: return t('ui.analystTargets.instrument.other', { type: normalized });
  }
}

/** Nota del panel traducida; null si el backend no mandó nota. */
export function analystTargetsNote(data: AnalystTargetsCopyInput | null | undefined, t: TranslateFn): string | null {
  if (!data) return null;
  switch (data.note_code) {
    case 'fetch_failed':
      return t('ui.analystTargets.notes.fetchFailed');
    case 'not_equity':
      return t('ui.analystTargets.notes.notEquity', { symbol: data.symbol, instrument: instrumentText(data.instrument_type, t) });
    case 'consensus_only':
      return t('ui.analystTargets.notes.consensusOnly');
    case 'no_targets':
      return t('ui.analystTargets.notes.noTargets');
    case 'with_press':
      return t('ui.analystTargets.notes.withPress');
    default:
      return data.note ?? null;
  }
}

/** Fuente del precio de referencia traducida; null si el backend no la da. */
export function referencePriceSourceText(data: AnalystTargetsCopyInput, t: TranslateFn): string | null {
  if (data.reference_price_source_code === 'market_at_fetch') return t('ui.analystTargets.referencePriceSource.marketAtFetch');
  return data.reference_price_source ?? null;
}
