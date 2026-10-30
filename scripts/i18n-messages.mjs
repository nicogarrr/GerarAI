/**
 * Cargador compartido de diccionarios i18n para guards y scripts.
 *
 * Los diccionarios viven repartidos por área en lib/i18n/messages/<locale>/
 * <area>.json (el nombre del archivo es el prefijo de clave). Este cargador
 * los fusiona en un único objeto { <area>: { ...claves } } con la misma forma
 * que tenía el antiguo lib/i18n/es.json, para que los guards no dependan del
 * reparto físico en archivos.
 */
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

const MESSAGES_DIR = join(process.cwd(), 'lib/i18n/messages');

/** Devuelve { areas: string[], dict: { [area]: objeto } } de un locale. */
export function loadMessages(locale = 'es') {
  const dir = join(MESSAGES_DIR, locale);
  const areas = readdirSync(dir)
    .filter((name) => name.endsWith('.json'))
    .map((name) => name.slice(0, -'.json'.length))
    .sort();
  const dict = {};
  for (const area of areas) {
    dict[area] = JSON.parse(readFileSync(join(dir, `${area}.json`), 'utf8'));
  }
  return { areas, dict };
}
