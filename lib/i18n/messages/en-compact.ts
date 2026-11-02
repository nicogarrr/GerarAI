/**
 * Inglés compacto ESTÁTICO: lo usan el servidor, los tests y los scripts de
 * Node (condición `default` de `#i18n-en-compact` en package.json). El
 * navegador resuelve `en-compact.browser.ts` y lo descarga solo si hace falta.
 */
import compactEn from './en.compact.json' with { type: 'json' };

/** Valores del inglés por área, en el orden de las hojas del español. */
export type CompactEnglish = Record<string, (string | null)[]>;

export const bundledCompactEnglish: CompactEnglish | null = compactEn as CompactEnglish;

export function loadCompactEnglish(): Promise<CompactEnglish> {
  return Promise.resolve(compactEn as CompactEnglish);
}
