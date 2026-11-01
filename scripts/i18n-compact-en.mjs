/** Generate the English value table using Spanish's existing key structure. */
import { readFileSync, writeFileSync, readdirSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const root = new URL('../lib/i18n/messages/', import.meta.url);
export function compactEnglish() {
  const result = {};
  for (const file of readdirSync(new URL('es/', root)).filter(f => f.endsWith('.json')).sort()) {
    const es = JSON.parse(readFileSync(new URL(`es/${file}`, root), 'utf8'));
    const en = JSON.parse(readFileSync(new URL(`en/${file}`, root), 'utf8'));
    const values = [];
    function visit(reference, translated) {
      if (typeof reference === 'string') {
        if (translated !== undefined && typeof translated !== 'string') throw new Error(`Invalid English leaf in ${file}`);
        values.push(translated ?? null);
        return;
      }
      for (const key of Object.keys(translated ?? {})) {
        if (!(key in reference)) throw new Error(`Unknown English key ${file}:${key}`);
      }
      for (const [key, value] of Object.entries(reference)) visit(value, translated?.[key]);
    }
    visit(es, en);
    result[file.slice(0, -5)] = values;
  }
  return JSON.stringify(result) + '\n';
}
if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) {
  writeFileSync(new URL('en.compact.json', root), compactEnglish());
}
