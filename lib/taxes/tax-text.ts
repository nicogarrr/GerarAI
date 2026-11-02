import type { Locale } from '@/lib/i18n/locale';
import { humanizeTaxText } from '@/lib/taxes/humanize-text';
import data from '@/lib/taxes/tax-text-en.json';

/**
 * Textos del motor fiscal (motivos, notas y avisos del Modelo 720) en el idioma
 * de la interfaz. El backend los compone en castellano; en castellano solo se
 * humanizan las claves internas (humanizeTaxText). En inglés se traducen las
 * frases conocidas, tal cual o por plantilla con sus datos ({currency},
 * {list}…); un texto nuevo que aún no está en la tabla sale tal cual, sin
 * claves internas.
 */
const EXACT: Record<string, string> = data.exact;

const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

const TEMPLATES = (data.templates as [string, string][]).map(([es, en]) => {
  const names: string[] = [];
  const pattern = escape(es).replace(/\\\{(\w+)\\\}/g, (_match, name: string) => {
    names.push(name);
    return '(.+?)';
  });
  return { re: new RegExp(`^${pattern}$`), names, en };
});

export function taxText(text: string, locale: Locale): string {
  if (locale !== 'en') return humanizeTaxText(text);
  const exact = EXACT[text];
  if (exact) return exact;
  for (const template of TEMPLATES) {
    const match = template.re.exec(text);
    if (match) return template.en.replace(/\{(\w+)\}/g, (_m, name: string) => match[template.names.indexOf(name) + 1] ?? '');
  }
  // Sin traducción conocida: solo se limpian las claves internas, en inglés
  // (humanizeTaxText metería castellano en un texto ya traducido).
  return EN_KEYS.reduce((acc, [pattern, value]) => acc.replace(pattern, value), text);
}

const EN_KEYS: Array<[RegExp, string]> = [
  [/'?\btax_declarant\b'?(?:\.\w+)?/g, 'your declarant data'],
  [/\bcash[-:]([A-Z]{3})\b/g, '$1 cash'],
];
