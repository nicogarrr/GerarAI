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

import { createContext, use, useContext, useEffect, useMemo, useSyncExternalStore, type ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import { loadCompactEnglish } from '#i18n-en-compact';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { createFormatters, type Formatters } from '../format.ts';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { DEFAULT_LOCALE, type Locale } from './locale.ts';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { createTranslator, type TranslateFn } from './translate.ts';
import {
  I18N_AREAS,
  getSpanishRecoveryVersion,
  hasEnglishMessages,
  hasSpanishAreas,
  loadSpanishAreas,
  registerCompactEnglish,
  subscribeSpanishRecovery,
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
} from './messages/index.ts';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { spanishAreasForPath } from './route-areas.ts';

const LocaleContext = createContext<Locale>(DEFAULT_LOCALE);

// Una promesa estable por carga (se queda en caché al resolverse): use()
// necesita la misma promesa en cada reintento de render. Si falla, se olvida
// para reintentar.
const ready = new Map<string, Promise<void>>();

function ensure(key: string, load: () => Promise<void>): Promise<void> {
  let promise = ready.get(key);
  if (!promise) {
    promise = load();
    promise.catch(() => ready.delete(key));
    ready.set(key, promise);
  }
  return promise;
}

function ensureSpanishAreas(areas: readonly string[]): Promise<void> {
  return ensure(`es:${areas.join(',')}`, () => loadSpanishAreas(areas));
}

/** Carga (una vez) el diccionario inglés del navegador y lo registra. */
function ensureEnglish(): Promise<void> {
  // El inglés compacto se expande sobre la estructura del castellano entero.
  return ensure('en', () => Promise.all([loadSpanishAreas(I18N_AREAS), loadCompactEnglish()])
    .then(([, compact]) => registerCompactEnglish(compact)));
}

// En desarrollo se cargan todas las áreas: así una clave nueva funciona sin
// regenerar el mapa (el test y `npm run prebuild` lo mantienen al día).
const DEV_ALL_AREAS = process.env.NODE_ENV !== 'production';

// Fuera de producción no hace falta la ruta (y así los tests que simulan
// next/navigation sin usePathname siguen funcionando).
const useAreasPathname: () => string | null = DEV_ALL_AREAS ? () => null : usePathname;

export function LocaleProvider({ locale, children }: { locale: Locale; children: ReactNode }) {
  const pathname = useAreasPathname();
  // Con la página ya pintada, el resto de áreas se baja en segundo plano: la
  // siguiente navegación no espera a ningún diccionario. (Los hooks van antes
  // de los use() que pueden suspender.)
  useEffect(() => {
    if (hasSpanishAreas(I18N_AREAS)) return undefined;
    const load = () => { void loadSpanishAreas(I18N_AREAS).catch(() => {}); };
    if (typeof window.requestIdleCallback === 'function') {
      const id = window.requestIdleCallback(load, { timeout: 4000 });
      return () => window.cancelIdleCallback(id);
    }
    const id = window.setTimeout(load, 1500);
    return () => window.clearTimeout(id);
  }, []);
  // En el navegador el castellano llega por áreas: se espera a las de esta ruta
  // antes de pintar (en la hidratación React conserva el HTML del servidor;
  // al navegar, la página anterior sigue a la vista hasta tenerlas). En el
  // servidor están todas y no se espera nada.
  const areas = DEV_ALL_AREAS ? I18N_AREAS : spanishAreasForPath(pathname);
  // El inglés depende del castellano entero: esperar una sola promesa para
  // ambos. Dos use() condicionales hacían que, al resolverse el castellano,
  // la promesa inglesa ocupase el slot anterior durante el reintento React.
  if (locale === 'en') {
    if (!hasEnglishMessages()) use(ensureEnglish());
  } else if (!hasSpanishAreas(areas)) {
    use(ensureSpanishAreas(areas));
  }

  return <LocaleContext.Provider value={locale}>{children}</LocaleContext.Provider>;
}

/** Locale activo («es» | «en»). */
export function useLocale(): Locale {
  return useContext(LocaleContext);
}

/** t() ligada al locale activo. */
export function useT(): TranslateFn {
  const locale = useLocale();
  // Solo cambia si hubo que descargar un área que la ruta no traía (ver
  // recoverSpanishArea): entonces se vuelve a pintar con el texto ya cargado.
  const recovery = useSyncExternalStore(subscribeSpanishRecovery, getSpanishRecoveryVersion, () => 0);
  return useMemo(() => {
    void recovery;
    return createTranslator(locale);
  }, [locale, recovery]);
}

/** Funciones de formato (números, fechas, importes) ligadas al locale. */
export function useFormat(): Formatters {
  const locale = useLocale();
  return useMemo(() => createFormatters(locale), [locale]);
}
