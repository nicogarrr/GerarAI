/**
 * Avisos de la calibración LLM del paper trading (Pro Picks). El backend
 * (paper_calibration_service.py) los manda en castellano con sus cifras; en
 * inglés se reescriben con el catálogo. En castellano, o con un aviso que no se
 * reconoce, pasa el texto del backend tal cual.
 */
// Rutas relativas con extensión: scripts/paper-calibration-ui.test.ts carga la vista con node --test.
import type { Locale } from '../i18n/locale';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { createTranslator } from '../i18n/translate.ts';

const INSUFFICIENT = /^Muestra insuficiente \((\d+) cerradas, mínimo (\d+)\): la calibración es orientativa$/;
const FEW_IN_BIN = /^menos de (\d+) cerradas: tasa N\/D$/;

export function paperCalibrationNotice(text: string, locale: Locale): string {
  if (locale !== 'en') return text;
  const t = createTranslator(locale);
  const insufficient = INSUFFICIENT.exec(text);
  if (insufficient) return t('propicks.paper.calNoticeInsufficient', { closed: insufficient[1], min: insufficient[2] });
  const few = FEW_IN_BIN.exec(text);
  if (few) return t('propicks.paper.binNoticeFew', { min: few[1] });
  return text;
}
