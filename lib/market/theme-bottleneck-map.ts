/**
 * Cruce explícito Temas de mercado <-> Cuellos de botella.
 *
 * Mapeo curado a mano entre las 17 cestas de /temas y los 6 temas de escasez
 * de /cuellos. Es deliberadamente conservador: solo se enlaza cuando el
 * solape es directo y explicable (p. ej. la cesta "Materiales críticos" son
 * mineras de cobre/litio/tierras raras/uranio -> "Minerales"). "Transporte"
 * no tiene cesta equivalente y no se enlaza. Sin inferencia por LLM.
 */
import type { TranslateFn } from '@/lib/i18n/translate';
import type { TranslationKey } from '@/lib/i18n/t';

export const THEME_TO_BOTTLENECK: Record<string, string> = {
  semiconductores: 'Semiconductores',
  'centros-de-datos': 'Centros de datos',
  materiales: 'Minerales',
  utilities: 'Energía',
  nuclear: 'Energía',
  espacio: 'Industria aeroespacial',
  defensa: 'Industria aeroespacial',
};

export interface RelatedTheme {
  id: string;
  name: string;
}

/** Dirección inversa, con el nombre visible de cada cesta relacionada. */
export const BOTTLENECK_TO_THEMES: Record<string, RelatedTheme[]> = {
  Semiconductores: [{ id: 'semiconductores', name: 'Semiconductores' }],
  'Centros de datos': [{ id: 'centros-de-datos', name: 'Centros de datos' }],
  Minerales: [{ id: 'materiales', name: 'Materiales críticos' }],
  Energía: [
    { id: 'utilities', name: 'Energía y utilities' },
    { id: 'nuclear', name: 'Nuclear' },
  ],
  'Industria aeroespacial': [
    { id: 'espacio', name: 'Espacio' },
    { id: 'defensa', name: 'Defensa y aeroespacial' },
  ],
};

/** Clave de traducción del nombre de cada cesta de /temas, por id. */
const BASKET_KEYS: Record<string, TranslationKey> = {
  semiconductores: 'themes.basketNames.semiconductors',
  cuantica: 'themes.basketNames.quantum',
  ia: 'themes.basketNames.ai',
  'centros-de-datos': 'themes.basketNames.dataCenters',
  ciberseguridad: 'themes.basketNames.cybersecurity',
  salud: 'themes.basketNames.health',
  'cloud-saas': 'themes.basketNames.cloudSaas',
  robotica: 'themes.basketNames.robotics',
  infraestructuras: 'themes.basketNames.infrastructure',
  defensa: 'themes.basketNames.defense',
  materiales: 'themes.basketNames.materials',
  adtech: 'themes.basketNames.adtech',
  utilities: 'themes.basketNames.utilities',
  espacio: 'themes.basketNames.space',
  drones: 'themes.basketNames.drones',
  fintech: 'themes.basketNames.fintech',
  nuclear: 'themes.basketNames.nuclear',
};

/**
 * Nombre visible de una cesta. El catálogo del motor manda el nombre en
 * español; con el inglés elegido se traduce por id. Una cesta nueva sin
 * traducción conserva el nombre que manda el motor.
 */
export function basketName(id: string, fallback: string, t: TranslateFn): string {
  return Object.hasOwn(BASKET_KEYS, id) ? t(BASKET_KEYS[id]) : fallback;
}

/** Clave de traducción de cada tema de escasez de /cuellos (nombre del motor -> clave). */
const BOTTLENECK_KEYS: Record<string, TranslationKey> = {
  Semiconductores: 'bottlenecks.themeNames.semiconductors',
  Energía: 'bottlenecks.themeNames.energy',
  Minerales: 'bottlenecks.themeNames.minerals',
  Transporte: 'bottlenecks.themeNames.transport',
  'Centros de datos': 'bottlenecks.themeNames.dataCenters',
  'Industria aeroespacial': 'bottlenecks.themeNames.aerospace',
};

/** Nombre visible de un tema de escasez; uno desconocido se muestra tal cual. */
export function bottleneckThemeName(theme: string, t: TranslateFn): string {
  return Object.hasOwn(BOTTLENECK_KEYS, theme) ? t(BOTTLENECK_KEYS[theme]) : theme;
}
