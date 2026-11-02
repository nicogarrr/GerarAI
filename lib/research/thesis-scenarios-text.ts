/**
 * Escenarios de la tesis: el backend manda los nombres de escenario en
 * castellano (TITLES de thesis_scenario_service.py) y el aviso de coherencia
 * de thesis_projection_service.py, y el motivo de cada celda N/D (_view y
 * _lineage_reason). En inglés se traducen; en castellano, y con un texto que no
 * se reconoce, pasa el del backend tal cual.
 */
import type { Locale } from '@/lib/i18n/locale';

const NAMES_EN: Record<string, string> = { Pesimista: 'Bear', Central: 'Base', Optimista: 'Bull' };
const PROBLEMS_EN: Record<string, string> = { 'precio objetivo': 'target price', 'ingresos proyectados': 'projected revenue' };
const REASONS_EN: Record<string, string> = {
  'Fila anual sin traza unica de la misma versión y fecha de corte.': 'Annual row without a single trace from the same version and cutoff date.',
  'La cadena anual de ingresos esta incompleta o duplicada.': 'The annual revenue chain is incomplete or duplicated.',
  'Un ejercicio anterior usa crecimiento sin linaje determinista acreditado.': 'An earlier year uses growth without verified deterministic lineage.',
  'Falta el valor persistido o su valor en la traza.': 'The stored value or its value in the trace is missing.',
  'La cifra anual no coincide con la traza de esta versión.': 'The annual figure does not match this version\'s trace.',
  'La fila no esta etiquetada como proyección inferida.': 'The row is not labelled as an inferred projection.',
  'Falta la fecha de corte.': 'The cutoff date is missing.',
  'Falta el ancla de ingresos OFICIAL con fuente y fecha.': 'The OFFICIAL revenue anchor with source and date is missing.',
  'Crecimiento sin linaje completo persistido: faltan la procedencia de los extremos historicos del CAGR o una tasa OFICIAL con fuente y fecha.': 'Growth without complete stored lineage: the provenance of the CAGR\'s historical endpoints or an OFFICIAL rate with source and date is missing.',
  'Falta el ancla FCF OFICIAL con fuente y fecha.': 'The OFFICIAL FCF anchor with source and date is missing.',
  'Las anclas de FCF e ingresos no corresponden al mismo ejercicio.': 'The FCF and revenue anchors are not from the same fiscal year.',
  'Margen FCF ausente o sin linaje determinista acreditado (puede incluir inputs LLM).': 'FCF margin missing or without verified deterministic lineage (may include LLM inputs).',
  'Faltan resultado neto o acciones OFICIALES con fuente y fecha.': 'OFFICIAL net income or shares with source and date are missing.',
};
const COHERENCE = /^los escenarios no quedan ordenados bear <= base <= bull en (.+); se muestran los valores calculados, sin reordenar$/;

export function scenarioNameText(name: string, locale: Locale): string {
  if (locale !== 'en') return name;
  return Object.hasOwn(NAMES_EN, name) ? NAMES_EN[name] : name;
}

export function scenarioCoherenceText(text: string, locale: Locale): string {
  if (locale !== 'en') return text;
  const match = COHERENCE.exec(text);
  if (!match) return text;
  const problems = match[1].split(' y ');
  if (!problems.every((problem) => Object.hasOwn(PROBLEMS_EN, problem))) return text;
  return `scenarios are not ordered bear <= base <= bull in ${problems.map((problem) => PROBLEMS_EN[problem]).join(' and ')}; the computed values are shown, not reordered`;
}

/** Motivo de una celda N/D (title y texto para lector de pantalla). */
export function scenarioReasonText(text: string, locale: Locale): string {
  if (locale !== 'en') return text;
  return Object.hasOwn(REASONS_EN, text) ? REASONS_EN[text] : text;
}
