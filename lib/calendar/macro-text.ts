/**
 * Calendario macro (macro_calendar_service.py): el backend manda en castellano
 * el título de cada evento, el detalle del FOMC y el nombre de la fuente que
 * se nombra cuando está caída. En inglés se muestran con las mismas palabras
 * que ya usa el aviso de Telegram (macro_reminders.py); lo que no se reconoce,
 * y todo en castellano, pasa tal cual.
 */
import type { Locale } from '@/lib/i18n/locale';

const TEXT_EN: Record<string, string> = {
  'Reunión del FOMC (decisión de tipos)': 'FOMC meeting (rate decision)',
  'IPC de EE. UU. (inflación)': 'US CPI (inflation)',
  'Informe de empleo de EE. UU.': 'US jobs report',
  'IPP de EE. UU. (precios al productor)': 'US PPI (producer prices)',
  'JOLTS: ofertas de empleo': 'JOLTS: job openings',
  'Índice de costes laborales': 'Employment Cost Index',
  'Con proyecciones económicas': 'With economic projections',
};

const SOURCES_EN: Record<string, string> = {
  'Reserva Federal (FOMC)': 'Federal Reserve (FOMC)',
};

/** Título o detalle de un evento macro en el idioma de la pantalla. */
export function macroEventText(text: string, locale: Locale): string {
  return locale === 'en' ? (TEXT_EN[text] ?? text) : text;
}

/** Nombre de una fuente del calendario macro (aviso de fuente caída o parcial). */
export function macroSourceName(name: string, locale: Locale): string {
  return locale === 'en' ? (SOURCES_EN[name] ?? name) : name;
}
