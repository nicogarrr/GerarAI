import type { Locale } from '@/lib/i18n/locale';
/** El backend publica las limitaciones del 13F como constante revisada en
 *  inglés; en UI van en español (F33). Texto desconocido: se muestra tal cual,
 *  nunca se oculta una limitación. */
const LIMITATION_LABELS: Record<string, string> = {
    'Quarterly cadence with up to a 45-day reporting lag':
        'Periodicidad trimestral con hasta 45 días de retardo en la declaración',
    'Long-only US-listed positions; no shorts, no non-13F securities':
        'Solo posiciones largas cotizadas en EE. UU.; sin cortos ni valores fuera del 13F',
    'Holdings as filed: CUSIP + issuer name; tickers never inferred':
        'Posiciones tal como se declararon: CUSIP y nombre del emisor; nunca se infieren tickers',
    'Amendments are separate immutable filings':
        'Las enmiendas son declaraciones inmutables independientes',
};

/** investor_portfolio.py escribe en castellano la nota de cada fila (opciones,
 *  diferencias entre 13F, códigos del Form 4, posiciones curadas) y el aviso de
 *  los gestores sin 13F. Con inglés se traducen; un texto nuevo sale tal cual. */
export const OWNERSHIP_TEXT_EN: Record<string, string> = {
    'Comparación incompleta: faltan acciones válidas en uno o ambos periodos; no se infiere una compra, venta ni posición sin cambios.':
        'Incomplete comparison: valid share counts are missing in one or both periods; no purchase, sale or unchanged position is inferred.',
    'Comparación incompleta en algunas posiciones: consulta el aviso de cada fila.':
        'Incomplete comparison for some positions: see each row notice.',
    'Opción (put/call): importe nocional, no posición en acciones.': 'Option (put/call): notional amount, not a share position.',
    'Diferencia entre dos 13F trimestrales (fecha = cierre del trimestre, no del trade).':
        'Difference between two quarterly 13Fs (date = quarter end, not the trade date).',
    'Codigo G (donacion/transferencia): no es compra ni venta en mercado.': 'Code G (gift/transfer): not an open-market purchase or sale.',
    'Codigo J (otra adquisicion o disposicion; ver notas del Form 4): no es mercado abierto.':
        'Code J (other acquisition or disposition; see the Form 4 notes): not open market.',
    'Titular: Donald J. Trump Revocable Trust (propiedad indirecta). 41,5% sobre 276.497.911 acciones en circulacion segun el 13D/A nº 3 (evento 2025-12-18, presentado 2025-12-22). No se ha verificado ningun 13D/A posterior.':
        'Holder: Donald J. Trump Revocable Trust (indirect ownership). 41.5% of 276,497,911 shares outstanding per 13D/A No. 3 (event 2025-12-18, filed 2025-12-22). No later 13D/A has been verified.',
    'Sin 13F: solo posiciones documentadas en 13D/Forms 3/4. El valor y el peso no están disponibles (N/D) mientras no haya valoracion con fuente; no es la cartera completa.':
        'No 13F: only positions documented in 13D/Forms 3/4. Value and weight are not available until there is a sourced valuation; this is not the full portfolio.',
};

/** Nota de una fila de la cartera de un inversor, en el idioma activo. */
export function ownershipNote(note: string, locale: Locale): string {
  return locale === 'en' ? OWNERSHIP_TEXT_EN[note] ?? note : note;
}

/** Traduce cada límite sin ocultar advertencias nuevas del proveedor. */
export function ownershipLimitations(value: string | string[] | null | undefined, locale: Locale = 'es', na = 'N/D'): string {
  if (!value) return '';
  const joined = Array.isArray(value) ? value.join('. ') : value;
  // En inglés el texto del backend ya es inglés (salvo el aviso de los
  // gestores sin 13F, que llega en castellano): solo se cambia el marcador.
  if (locale === 'en') return (OWNERSHIP_TEXT_EN[joined] ?? joined).replace(/\bSIN_DATOS\b/g, na);
  let text = joined.replace(/\bSIN_DATOS\b/g, na);
  for (const [original, translated] of Object.entries(LIMITATION_LABELS)) {
    text = text.replaceAll(original, translated);
  }
  return text;
}
