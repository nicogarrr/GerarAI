/**
 * Escenarios de la tesis: el backend manda los nombres de escenario en
 * castellano (TITLES de thesis_scenario_service.py) y el aviso de coherencia
 * de thesis_projection_service.py. En inglés se traducen; en castellano, y con
 * un texto que no se reconoce, pasa el del backend tal cual.
 */
import type { Locale } from '@/lib/i18n/locale';

const NAMES_EN: Record<string, string> = { Pesimista: 'Bear', Central: 'Base', Optimista: 'Bull' };
const PROBLEMS_EN: Record<string, string> = { 'precio objetivo': 'target price', 'ingresos proyectados': 'projected revenue' };
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
