/**
 * Inglés compacto en el NAVEGADOR (condición `browser` de `#i18n-en-compact`):
 * no va en el chunk común; `loadCompactEnglish()` lo pide como chunk aparte
 * (con hash, cacheable). Si la página se sirvió en inglés (<html lang="en">)
 * la descarga empieza ya al evaluar este módulo, antes de hidratar.
 */
import type { CompactEnglish } from './en-compact.ts';

export type { CompactEnglish };

export const bundledCompactEnglish: CompactEnglish | null = null;

let pending: Promise<CompactEnglish> | null = null;

export function loadCompactEnglish(): Promise<CompactEnglish> {
  pending ??= import('./en.compact.json').then((module) => module.default as CompactEnglish);
  return pending;
}

if (typeof document !== 'undefined' && document.documentElement.lang === 'en') {
  void loadCompactEnglish();
}
