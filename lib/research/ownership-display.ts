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

/** Traduce cada límite sin ocultar advertencias nuevas del proveedor. */
export function ownershipLimitations(value: string | string[] | null | undefined, locale: Locale = 'es', na = 'N/D'): string {
  if (!value) return '';
  const joined = Array.isArray(value) ? value.join('. ') : value;
  // En inglés el texto del backend ya es inglés: solo se cambia el marcador.
  if (locale === 'en') return joined.replace(/\bSIN_DATOS\b/g, na);
  let text = joined.replace(/\bSIN_DATOS\b/g, na);
  for (const [original, translated] of Object.entries(LIMITATION_LABELS)) {
    text = text.replaceAll(original, translated);
  }
  return text;
}
