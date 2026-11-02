import type { Locale } from '@/lib/i18n/locale';
import { humanizeTaxText } from '@/lib/taxes/humanize-text';
import data from '@/lib/taxes/tax-text-en.json';

/**
 * Textos del motor fiscal (motivos, notas y avisos del Modelo 720, del IRPF y
 * del resumen del informe) en el idioma
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
    return '((?:(?!; ).)+?)';
  });
  return { re: new RegExp(`^${pattern}$`), names, en };
});

/** Traducción de una frase conocida (tal cual o por plantilla), o null. */
function known(text: string): string | null {
  const exact = EXACT[text];
  if (exact) return exact;
  for (const template of TEMPLATES) {
    const match = template.re.exec(text);
    if (match) {
      return template.en.replace(/\{(\w+)\}/g, (_m, name: string) => {
        const value = match[template.names.indexOf(name) + 1] ?? '';
        return EXACT[value] ?? value;
      });
    }
  }
  return null;
}

export function taxText(text: string, locale: Locale): string {
  if (locale !== 'en') return humanizeTaxText(text);
  const whole = known(text);
  if (whole !== null) return whole;
  // Motivos encadenados con «; » (libro de divisas): se traduce cada uno,
  // probando primero los tramos más largos (un motivo puede llevar «; » dentro).
  if (text.includes('; ')) {
    const parts = text.split('; ');
    const out: string[] = [];
    let changed = false;
    for (let i = 0; i < parts.length;) {
      let j = parts.length;
      let hit: string | null = null;
      for (; j > i; j -= 1) {
        hit = known(parts.slice(i, j).join('; '));
        if (hit !== null) break;
      }
      if (hit !== null) {
        out.push(hit);
        changed = true;
        i = j;
      } else {
        out.push(cleanKeys(parts[i] ?? ''));
        i += 1;
      }
    }
    if (changed) return out.join('; ');
  }
  // Sin traducción conocida: solo se limpian las claves internas, en inglés
  // (humanizeTaxText metería castellano en un texto ya traducido).
  return cleanKeys(text);
}

function cleanKeys(text: string): string {
  return EN_KEYS.reduce((acc, [pattern, value]) => acc.replace(pattern, value), text);
}

const EN_KEYS: Array<[RegExp, string]> = [
  [/'?\btax_declarant\b'?(?:\.\w+)?/g, 'your declarant data'],
  [/\bcash[-:]([A-Z]{3})\b/g, '$1 cash'],
];
