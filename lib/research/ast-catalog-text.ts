import type { AstsAnalysis } from '@/lib/actions/asts-orbits.actions';
import type { Locale } from '@/lib/i18n/locale';

// El backend (asts_catalog_service / asts_llm_service) escribe en castellano la
// nota de uso de las órbitas y la lectura determinista del catálogo. En inglés:
// la nota fija va por tabla y la lectura se rehace con los agregados que la
// misma respuesta ya trae. Lo demás (p. ej. la lectura generada por el modelo,
// que ya sale en el idioma activo) se pinta tal cual.

export const AST_USAGE_NOTE_ES =
  'Señal exploratoria calculada sobre elementos orbitales. BSTAR y derivadas son parámetros de ajuste, no telemetría ni confirmación de despliegue.';
const AST_USAGE_NOTE_EN =
  'Exploratory signal computed from orbital elements. BSTAR and derivatives are fit parameters, not telemetry or confirmation of deployment.';

/** Prefijo de la lectura determinista del backend (no de la del modelo). */
export const AST_DETERMINISTIC_PREFIX_ES = 'Catálogo CelesTrak del grupo AST descargado el ';

export function astUsageNote(note: string | null | undefined, locale: Locale): string | null {
  if (!note) return null;
  return locale === 'en' && note.trim() === AST_USAGE_NOTE_ES ? AST_USAGE_NOTE_EN : note;
}

type Reading = NonNullable<AstsAnalysis['analysis']>;

export function astCatalogReading(
  reading: Reading,
  fetchedAt: string | null | undefined,
  locale: Locale,
): { summary: string; observations: { text: string }[] } {
  const agg = reading.aggregates;
  if (locale !== 'en' || !agg || !fetchedAt || !reading.summary.startsWith(AST_DETERMINISTIC_PREFIX_ES)) {
    return { summary: reading.summary, observations: reading.observations };
  }
  // Mismo orden que el backend: familias por nombre, «N NOMBRE».
  const families = Object.entries(agg.families ?? {})
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([name, count]) => `${count} ${name}`)
    .join(', ');
  const inclination = `${agg.inclination_deg_min}° and ${agg.inclination_deg_max}°`;
  const motion = `${agg.mean_motion_rev_day_min} and ${agg.mean_motion_rev_day_max} rev/day`;
  return {
    summary:
      `CelesTrak catalog of the AST group downloaded on ${fetchedAt}: ${agg.count} objects (${families}). ` +
      `Orbital epochs between ${agg.epoch_min} and ${agg.epoch_max}. Inclination between ${inclination}, ` +
      `mean motion between ${motion}, maximum eccentricity ${agg.eccentricity_max}.`,
    observations: [
      { text: `Catalog families: ${families}.` },
      { text: `Most recent orbital epoch: ${agg.epoch_max}; oldest: ${agg.epoch_min}.` },
      { text: `Inclination between ${inclination}; mean motion between ${motion}.` },
    ],
  };
}
