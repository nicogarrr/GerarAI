// @ts-expect-error TS5097: node --test (--experimental-strip-types) necesita la extensión.
import { t as esT, type TranslationKey, type TranslationVars } from '../i18n/t.ts';

/** Traductor del idioma elegido; por defecto el español de referencia. */
type TiFn = (key: TranslationKey, vars?: TranslationVars) => string;

// F34: una ficha sin cotización vigente no puede mostrar salud 0/100 como dato.
const STALE_DAYS = 30;

function esDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split('-');
  return `${d}/${m}/${y}`;
}

export type ListingStatus = { stale: true; message: string } | { stale: false };

/**
 * ¿Hay una cotización actual (en vivo o de la última sesión) para el valor?
 * Precio > 0, fuente disponible y marca de tiempo dentro de STALE_DAYS.
 */
export function hasCurrentQuote(
  quote: { price?: number | null; timestamp?: number | null; status?: string | null } | null | undefined,
  now: Date,
): boolean {
  if (!quote || quote.status === 'unavailable') return false;
  const { price, timestamp } = quote;
  if (typeof price !== 'number' || !Number.isFinite(price) || price <= 0) return false;
  if (typeof timestamp !== 'number' || !Number.isFinite(timestamp)) return false;
  return (now.getTime() - timestamp * 1000) / 86_400_000 <= STALE_DAYS;
}

/**
 * Aviso «sin cotización vigente». Con una cotización actual en la cabecera
 * (`currentQuote`), el aviso no se muestra: pintaba «sin cierre conocido»
 * justo encima de «349,64 US$ · Mercado abierto». Las reglas de frescura del
 * backend (#2884/#2924) no cambian: esto solo decide el aviso de la ficha.
 */
export function listingStatus(
  exchange: string | null | undefined,
  priceAsOf: string | null | undefined,
  now: Date,
  currentQuote = false,
  ti: TiFn = esT,
  formatDate: (iso: string) => string = esDate,
): ListingStatus {
  if (currentQuote) return { stale: false };
  const unknownExchange = !exchange || ['UNKNOWN', 'UNKNOWN_EXCHANGE'].includes(exchange.trim().toUpperCase());
  const asOf = priceAsOf && /^\d{4}-\d{2}-\d{2}/.test(priceAsOf) ? priceAsOf : null;
  const ageDays = asOf ? (now.getTime() - Date.parse(`${asOf.slice(0, 10)}T00:00:00Z`)) / 86_400_000 : null;
  const old = ageDays !== null && ageDays > STALE_DAYS;
  if (!unknownExchange && !old) return { stale: false };
  return {
    stale: true,
    message: asOf
      ? ti('research.listingStale.withClose', { date: formatDate(asOf.slice(0, 10)) })
      : ti('research.listingStale.noClose'),
  };
}

export function healthText(score: number | null | undefined, status: ListingStatus): string {
  if (status.stale || score === null || score === undefined) return 'Sin datos';
  return `${score}/100`;
}
