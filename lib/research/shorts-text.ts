/**
 * Posiciones cortas públicas (short_positions_service.py y cnmv_shorts.py):
 * el backend manda en castellano el motivo del estado y la nota de la
 * fuente. En inglés se traducen; en castellano, y con un texto que no se
 * reconoce, pasa el del backend tal cual.
 *
 * Los textos viven en los diccionarios (shorts.backendText.*) y aquí solo se
 * cruzan, igual que lib/research/ownership-display.ts: el guard de i18n no
 * cuenta literales de este archivo y los techos no se tocan.
 */
import type { Locale } from '@/lib/i18n/locale';
// Import relativo con atributo: este módulo también se ejecuta en tests con
// node --experimental-strip-types, que no resuelve el alias `@/`.
import esShorts from '../i18n/messages/es/shorts.json' with { type: 'json' };
import enShorts from '../i18n/messages/en/shorts.json' with { type: 'json' };

const TEXT_KEYS = [
  'finraDateInvalid',
  'lookupDateInvalid',
  'noMapping',
  'sourceUnverifiable',
  'lookupWindowLimit',
  'noStoredLookup',
  'dailyVolumeNote',
  'cnmvScopeNote',
  'finraSettlementStale',
] as const;

// Uso por literal para el guard de i18n (claves consumidas por iteración,
// igual que OWNERSHIP_BACKEND_TEXT_KEY_LITERALS): sin estas cadenas el guard
// las marcaría como huérfanas nuevas.
export const SHORTS_BACKEND_TEXT_KEY_LITERALS = [
  'shorts.backendText.finraDateInvalid',
  'shorts.backendText.lookupDateInvalid',
  'shorts.backendText.noMapping',
  'shorts.backendText.sourceUnverifiable',
  'shorts.backendText.lookupWindowLimit',
  'shorts.backendText.noStoredLookup',
  'shorts.backendText.dailyVolumeNote',
  'shorts.backendText.cnmvScopeNote',
  'shorts.backendText.finraSettlementStale',
] as const;

const backendText = (area: typeof esShorts, key: string): string =>
  (area.backendText as Record<string, string>)[key];

/** Motivo/nota del backend (castellano) -> inglés. */
const SHORTS_EN: Record<string, string> = Object.fromEntries(
  TEXT_KEYS.map((key) => [backendText(esShorts, key), backendText(enShorts, key)]),
);

export function shortsText<T extends string | null | undefined>(text: T, locale: Locale): T | string {
  if (locale !== 'en' || !text) return text;
  return Object.hasOwn(SHORTS_EN, text) ? SHORTS_EN[text] : text;
}
