'use client';

/**
 * i18n para client components.
 *
 * `LocaleProvider` lo monta app/layout.tsx con el locale leído de la cookie en
 * el servidor. Los componentes usan los hooks:
 *
 *   const t = useT();        // t('common.states.loading')
 *   const locale = useLocale();
 *   const fmt = useFormat(); // formatMoney, formatDate, ... ligadas al locale
 *
 * Para CAMBIAR el idioma: escribir la cookie `gerarai_locale` y llamar a
 * router.refresh() (lo hace components/settings/LanguageForm.tsx).
 */

import { createContext, use, useContext, useMemo, type ReactNode } from 'react';
import { loadCompactEnglish } from '#i18n-en-compact';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { createFormatters, type Formatters } from '../format.ts';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { DEFAULT_LOCALE, type Locale } from './locale.ts';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { createTranslator, type TranslateFn } from './translate.ts';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { hasEnglishMessages, registerCompactEnglish } from './messages/index.ts';

const LocaleContext = createContext<Locale>(DEFAULT_LOCALE);

let englishReady: Promise<void> | null = null;

/** Carga (una vez) el diccionario inglés del navegador y lo registra. */
function ensureEnglish(): Promise<void> {
  englishReady ??= loadCompactEnglish().then(registerCompactEnglish);
  return englishReady;
}

export function LocaleProvider({ locale, children }: { locale: Locale; children: ReactNode }) {
  // En el navegador el inglés no va en el chunk común: si el locale es «en» y
  // aún no está, se espera a su chunk antes de pintar (en la hidratación React
  // conserva el HTML del servidor mientras tanto; no hay parpadeo al español).
  if (locale === 'en' && !hasEnglishMessages()) use(ensureEnglish());
  return <LocaleContext.Provider value={locale}>{children}</LocaleContext.Provider>;
}

/** Locale activo («es» | «en»). */
export function useLocale(): Locale {
  return useContext(LocaleContext);
}

/** t() ligada al locale activo. */
export function useT(): TranslateFn {
  const locale = useLocale();
  return useMemo(() => createTranslator(locale), [locale]);
}

/** Funciones de formato (números, fechas, importes) ligadas al locale. */
export function useFormat(): Formatters {
  const locale = useLocale();
  return useMemo(() => createFormatters(locale), [locale]);
}
