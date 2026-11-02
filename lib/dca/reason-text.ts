/**
 * Señal y backtest DCA: cuando no hay datos, el backend (watchlist.py,
 * dca_backtest.py, dca_signal_engine.py) manda el motivo en castellano. En
 * inglés se traduce; en castellano, y con un texto que no se reconoce, pasa
 * el del backend tal cual.
 */
import type { Locale } from '@/lib/i18n/locale';

const DCA_REASON_EN: Record<string, string> = {
  'Preparando la señal DCA: se está evaluando en segundo plano': 'Preparing the DCA signal: it is being evaluated in the background',
  'Aún sin histórico calculado: se rellena en la próxima evaluación': 'No history computed yet: it is filled in at the next evaluation',
  'Sin histórico de precios para este ticker': 'No price history for this ticker',
  'Historia insuficiente en ese rango: hacen falta al menos 2 meses con veredicto confirmado y compra.':
    'Not enough history in that range: at least 2 months with a confirmed verdict and a purchase are needed.',
  'sin meses confirmados': 'no confirmed months',
  // Salvedad de aciertos y backtest (watchlist.py, valor por defecto del modelo)
  'Histórico, hipotético. No es asesoramiento.': 'Historical, hypothetical. Not advice.',
};

export function dcaReasonText<T extends string | null | undefined>(text: T, locale: Locale): T | string {
  if (locale !== 'en' || !text) return text;
  return Object.hasOwn(DCA_REASON_EN, text) ? DCA_REASON_EN[text] : text;
}
