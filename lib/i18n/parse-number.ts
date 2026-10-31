/**
 * Parser de números escritos por el usuario, consciente del locale.
 *
 * - es-ES («es»): coma decimal, punto de miles en grupos exactos de 3.
 * - en-US («en»): punto decimal, coma de miles en grupos exactos de 3.
 *
 * Nunca reinterpreta una entrada ambigua: mejor un error visible que un
 * factor 1000 silencioso en dinero. Lo ambiguo depende del locale:
 * «1,234» en es-ES puede ser 1,234 decimal ó 1234 al estilo US (se rechaza);
 * «1.234» en en-US puede ser 1.234 decimal ó 1234 al estilo es-ES (se
 * rechaza). Excepción simétrica: «0,001» / «0.001» sí son decimales,
 * porque los miles nunca empiezan por 0.
 *
 * Se RECHAZA siempre: «1e3», «0x10», «1 000», «Infinity»: Number() los
 * aceptaba en silencio.
 */

export type LocalizedNumberError = 'empty' | 'invalid' | 'ambiguous';

export type ParseResult = { ok: true; value: number } | { ok: false; error: LocalizedNumberError };

const INT_PLAIN = /^\d+$/;
// Miles es-ES estrictos: grupos de 3 tras el primero («1.234», «12.345.678»).
const INT_GROUPS_ES = /^\d{1,3}(?:\.\d{3})+$/;
// Miles en-US estrictos: grupos de 3 tras el primero («1,234», «12,345,678»).
const INT_GROUPS_EN = /^\d{1,3}(?:,\d{3})+$/;

/** ¿El locale trabaja en inglés? Acepta «en», «en-US», «en-GB»... */
export function isEnglishLocale(locale: string): boolean {
  return locale.toLowerCase().startsWith('en');
}

function parseEs(trimmed: string): ParseResult {
  const negative = trimmed.startsWith('-');
  const body = negative ? trimmed.slice(1) : trimmed;
  const finish = (magnitude: number): ParseResult => {
    const signed = negative ? -magnitude : magnitude;
    return Number.isFinite(signed)
      ? { ok: true, value: signed }
      : { ok: false, error: 'invalid' };
  };

  const commaParts = body.split(',');
  if (commaParts.length > 2) return { ok: false, error: 'ambiguous' };
  if (commaParts.length === 2) {
    const [intPart, decPart] = commaParts;
    if (!INT_PLAIN.test(decPart)) return { ok: false, error: 'ambiguous' }; // «1,234.5», «32,», «1,2e3»
    if (intPart === '') return finish(Number(`0.${decPart}`)); // «,5»
    if (INT_GROUPS_ES.test(intPart)) {
      return finish(Number(`${intPart.replace(/\./g, '')}.${decPart}`)); // «1.234,56»
    }
    if (INT_PLAIN.test(intPart)) {
      // Coma seguida de exactamente 3 dígitos («1,234»): ¿decimal es-ES 1,234
      // o miles US 1234? Ambiguo y en dinero no se adivina; «0,001» sí es
      // decimal porque los miles nunca empiezan por 0.
      if (decPart.length === 3 && intPart !== '0') return { ok: false, error: 'ambiguous' };
      return finish(Number(`${intPart}.${decPart}`));
    }
    return { ok: false, error: 'ambiguous' }; // «12.34,5»: grupo de miles roto
  }

  const dotParts = body.split('.');
  if (dotParts.length === 1) {
    if (!INT_PLAIN.test(body)) return { ok: false, error: 'invalid' }; // «1e3», «abc», «0x10», «1 000», «+3», «-»
    return finish(Number(body));
  }
  if (dotParts.some((part) => part === '')) {
    // «.5» y «5.» se admiten; «1..2» no.
    if (dotParts.length === 2 && INT_PLAIN.test(dotParts[0] + dotParts[1]) && (dotParts[0] + dotParts[1]) !== '') {
      return finish(Number(`${dotParts[0] || '0'}.${dotParts[1] || '0'}`));
    }
    return { ok: false, error: 'ambiguous' };
  }
  if (dotParts.length > 2) {
    if (INT_GROUPS_ES.test(body)) return finish(Number(body.replace(/\./g, ''))); // «1.234.567»
    return { ok: false, error: 'ambiguous' };
  }
  // Un solo punto: grupos de 3 = miles es-ES («1.234» -> 1234); si no,
  // decimal con punto («32.5», «1.23», «1.2345»).
  if (INT_GROUPS_ES.test(body)) return finish(Number(body.replace(/\./g, '')));
  return finish(Number(body));
}

function parseEn(trimmed: string): ParseResult {
  const negative = trimmed.startsWith('-');
  const body = negative ? trimmed.slice(1) : trimmed;
  const finish = (magnitude: number): ParseResult => {
    const signed = negative ? -magnitude : magnitude;
    return Number.isFinite(signed)
      ? { ok: true, value: signed }
      : { ok: false, error: 'invalid' };
  };

  const dotParts = body.split('.');
  if (dotParts.length > 2) return { ok: false, error: 'ambiguous' }; // «1.2.3» no es en-US
  if (dotParts.length === 2) {
    const [intPart, decPart] = dotParts;
    if (intPart === '' && decPart === '') return { ok: false, error: 'ambiguous' }; // «.»
    if (decPart !== '' && !INT_PLAIN.test(decPart)) return { ok: false, error: 'ambiguous' }; // «1.234,5», «1.2e3»
    if (intPart === '') return finish(Number(`0.${decPart || '0'}`)); // «.5»
    if (INT_GROUPS_EN.test(intPart)) {
      return finish(Number(`${intPart.replace(/,/g, '')}.${decPart || '0'}`)); // «1,234.56», «1,234.»
    }
    if (INT_PLAIN.test(intPart)) {
      // Punto seguido de exactamente 3 dígitos («1.234»): ¿decimal en-US
      // 1.234 o miles es-ES 1234? Ambiguo y en dinero no se adivina;
      // «0.001» sí es decimal porque los miles nunca empiezan por 0.
      if (decPart.length === 3 && intPart !== '0') return { ok: false, error: 'ambiguous' };
      return finish(Number(`${intPart}.${decPart || '0'}`)); // «32.5», «5.»
    }
    return { ok: false, error: 'ambiguous' }; // «12,34.5»: grupo de miles roto
  }

  const commaParts = body.split(',');
  if (commaParts.length === 1) {
    if (!INT_PLAIN.test(body)) return { ok: false, error: 'invalid' }; // «1e3», «abc», «0x10», «1 000», «+3», «-»
    return finish(Number(body));
  }
  if (commaParts.some((part) => part === '')) return { ok: false, error: 'ambiguous' }; // «,5», «5,», «1,,2»
  if (INT_GROUPS_EN.test(body)) return finish(Number(body.replace(/,/g, ''))); // «1,234», «1,234,567»
  return { ok: false, error: 'ambiguous' }; // «12,34»: grupo de miles roto
}

/**
 * Parsea `value` según el locale y distingue el motivo del fallo para que el
 * formulario pueda explicar el formato esperado. Default «es».
 */
export function parseLocalizedNumberDetailed(value: string, locale: string = 'es'): ParseResult {
  const trimmed = value.trim();
  if (!trimmed) return { ok: false, error: 'empty' };
  return isEnglishLocale(locale) ? parseEn(trimmed) : parseEs(trimmed);
}

/**
 * Parsea números escritos por el usuario según el locale. Devuelve null ante
 * entrada vacía, inválida o AMBIGUA (nunca reinterpreta). Para distinguir el
 * motivo y mensajear al usuario, usa parseLocalizedNumberDetailed.
 */
export function parseLocalizedNumber(value: string, locale: string = 'es'): number | null {
  const result = parseLocalizedNumberDetailed(value, locale);
  return result.ok ? result.value : null;
}
