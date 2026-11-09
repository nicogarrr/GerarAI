import type { Metadata } from 'next';

// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { getT } from './server.ts';
import type { TranslationKey } from './t.ts';

/**
 * generateMetadata comun de las paginas: title y description traducidos.
 * Misma cadena que el patron inline (`const t = await getT(); return {...}`).
 */
export async function i18nPageMetadata(
  titleKey: TranslationKey,
  descriptionKey: TranslationKey,
): Promise<Metadata> {
  const t = await getT();
  return { title: t(titleKey), description: t(descriptionKey) };
}
