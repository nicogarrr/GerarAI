/**
 * Validación de identificadores fiscales españoles (DNI/NIE/CIF) para los
 * datos del declarante del modelo 720. Es un AVISO, no una barrera: puede
 * haber NIFs extranjeros legítimos, así que el guardado nunca se bloquea
 * desde aquí. El servidor solo rechaza longitudes absurdas o caracteres de
 * control (ver DeclarantInput en data-engine/app/api/routes/taxes.py).
 *
 * Reglas:
 * - DNI: 8 dígitos + letra de control ("TRWAGMYFPDXBNJZSQVHLCKE"[n % 23]).
 * - NIE: X/Y/Z + 7 dígitos + letra; X=0, Y=1, Z=2 para el cálculo.
 * - CIF: letra de tipo + 7 dígitos + control. Control numérico para
 *   A/B/E/H, alfabético ("JABCDEFGHI") para N/P/Q/R/S/W y cualquiera de
 *   los dos para el resto (C/D/F/G/J/U/V).
 */

export type SpanishTaxIdStatus = 'empty' | 'valid' | 'bad_control' | 'unknown_format';

const DNI_LETTERS = 'TRWAGMYFPDXBNJZSQVHLCKE';
const CIF_CONTROL_LETTERS = 'JABCDEFGHI';
const CIF_NUMERIC_ONLY = new Set(['A', 'B', 'E', 'H']);
const CIF_LETTER_ONLY = new Set(['N', 'P', 'Q', 'R', 'S', 'W']);

function controlLetterDNI(digits: string): string {
  return DNI_LETTERS[Number(digits) % 23];
}

function checkCIF(id: string): SpanishTaxIdStatus {
  const match = /^([ABCDEFGHJNPQRSUVW])(\d{7})([0-9A-J])$/.exec(id);
  if (!match) return 'unknown_format';
  const [, type, digits, control] = match;
  let sum = 0;
  for (let i = 0; i < 7; i += 1) {
    const d = Number(digits[i]);
    if (i % 2 === 0) {
      const doubled = d * 2;
      sum += Math.floor(doubled / 10) + (doubled % 10);
    } else {
      sum += d;
    }
  }
  const controlNum = (10 - (sum % 10)) % 10;
  const asDigit = control === String(controlNum);
  const asLetter = control === CIF_CONTROL_LETTERS[controlNum];
  if (CIF_NUMERIC_ONLY.has(type)) return asDigit ? 'valid' : 'bad_control';
  if (CIF_LETTER_ONLY.has(type)) return asLetter ? 'valid' : 'bad_control';
  return asDigit || asLetter ? 'valid' : 'bad_control';
}

/** Clasifica un identificador fiscal: vacío, válido, control erróneo o formato no español. */
export function checkSpanishTaxId(raw: string): SpanishTaxIdStatus {
  const id = raw.trim().toUpperCase().replace(/[\s.-]/g, '');
  if (!id) return 'empty';
  const dni = /^(\d{8})([A-Z])$/.exec(id);
  if (dni) return controlLetterDNI(dni[1]) === dni[2] ? 'valid' : 'bad_control';
  const nie = /^([XYZ])(\d{7})([A-Z])$/.exec(id);
  if (nie) {
    const prefix = String('XYZ'.indexOf(nie[1]));
    return controlLetterDNI(prefix + nie[2]) === nie[3] ? 'valid' : 'bad_control';
  }
  return checkCIF(id);
}

/** Texto del aviso suave para la UI; null cuando no hay nada que avisar. */
export function spanishTaxIdWarning(raw: string): string | null {
  const status = checkSpanishTaxId(raw);
  if (status === 'bad_control') {
    return 'El dígito de control no cuadra con el número. Revísalo antes de generar el 720; si es un identificador extranjero, ignora este aviso.';
  }
  if (status === 'unknown_format') {
    return 'No parece un DNI, NIE o CIF español. Si es un identificador fiscal extranjero, puedes ignorar este aviso.';
  }
  return null;
}

// K/L/M/T uncommon or legacy tax identifiers are treated as unknown format, not blocked.
