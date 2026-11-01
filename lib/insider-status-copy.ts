/**
 * Copy de estados no-ok del panel insider (F234). Puro y testeable: la
 * verdad del mensaje depende de QUÉ campos devolvió el backend.
 *
 * - degraded con contadores: «N con error de M escaneados».
 * - degraded solo con reason (catch global): cabecera explicativa común y
 *   la reason como DETALLE, nunca como sustituto — una razón técnica a pelo
 *   («AAPL: TypeError») sigue siendo opaca.
 * - partial sin señales: los escaneados no son «analizados» si algunos
 *   fallaron — se dice «X legibles de Y escaneados».
 */

// @ts-expect-error TS5097: extension explicita para node --experimental-strip-types (guards).
import { plural } from './utils/plural.ts';
// @ts-expect-error TS5097
import { createTranslator } from './i18n/translate.ts';
import type { Locale } from './i18n/locale.ts';

/** Inglés (Ajustes → Idioma): misma lógica, copia en insider.statusCopy.*. */
const tEn = () => createTranslator('en');
const REASON_KEY = {
    sec_bloquea_datacenter: 'insider.statusCopy.reason.secBlocksDatacenter',
    sec_limita_peticiones: 'insider.statusCopy.reason.secRateLimited',
    fuente_no_disponible: 'insider.statusCopy.reason.sourceUnavailable',
} as const;

export type InsiderStatusFields = {
    reason?: unknown;
    filings_scanned?: unknown;
    filings_parsed?: unknown;
    filings_failed?: unknown;
    filings_from_persisted?: unknown;
    latest_persisted_filing_date?: unknown;
};

type CountText = (value: unknown) => string;

const asNumber = (value: unknown): number | null =>
    typeof value === 'number' && Number.isFinite(value) ? value : null;

const REASON_COPY: Record<string, string> = {
    sec_bloquea_datacenter:
        'la SEC rechaza las consultas automáticas desde este servidor (HTTP 403)',
    sec_limita_peticiones: 'la SEC limitó las peticiones; reintenta en un minuto',
    fuente_no_disponible: 'la fuente no respondió',
};

/** Detalle apto para usuario: códigos conocidos en español; cualquier otra
 *  cadena (nombres de excepción, trazas) no se muestra nunca (F30). */
export function reasonCopy(reason: unknown, locale: Locale = 'es'): string | null {
    if (typeof reason !== 'string' || !reason) return null;
    if (locale === 'en') return Object.hasOwn(REASON_KEY, reason) ? tEn()(REASON_KEY[reason as keyof typeof REASON_KEY]) : null;
    return Object.hasOwn(REASON_COPY, reason) ? REASON_COPY[reason] : null;
}

export function degradedCopy(
    ticker: string,
    fields: InsiderStatusFields,
    countText: CountText,
    locale: Locale = 'es',
): { header: string; detail: string | null } {
    const scanned = asNumber(fields.filings_scanned);
    const failed = asNumber(fields.filings_failed);
    if (locale === 'en') {
        const header = scanned !== null && failed !== null
            ? tEn()('insider.statusCopy.degradedCounts', { ticker, failed: countText(failed), scanned: countText(scanned) })
            : tEn()('insider.statusCopy.degradedGeneric', { ticker });
        return { header, detail: reasonCopy(fields.reason, locale) };
    }
    // Con contadores sabemos que se escanearon Form 4 y todos fallaron; con
    // reason sola (catch global) el fallo pudo ser ANTES de consultar filings
    // (CIK, listado), asi que la cabecera abarca consulta y lectura.
    const header =
        scanned !== null && failed !== null
            ? `${ticker}: SEC EDGAR no devolvió ningún Form 4 legible (${countText(failed)} con error de ${plural(scanned, 'escaneado', 'escaneados')}).`
            : `${ticker}: no se pudieron consultar o leer las señales Form 4 de SEC EDGAR.`;
    return { header, detail: reasonCopy(fields.reason) };
}

export function analyzedCountCopy(
    status: string,
    fields: InsiderStatusFields,
    countText: CountText,
    locale: Locale = 'es',
): string {
    const scanned = asNumber(fields.filings_scanned);
    const parsed = asNumber(fields.filings_parsed);
    if (locale === 'en') {
        if (status === 'partial' && scanned !== null && parsed !== null) {
            return tEn()('insider.statusCopy.readableOfScanned', { parsed: countText(parsed), scanned: countText(scanned) });
        }
        return tEn()('insider.statusCopy.analyzed', { count: countText(fields.filings_scanned) });
    }
    if (status === 'partial' && scanned !== null && parsed !== null) {
        return `${plural(parsed, 'legible', 'legibles')} de ${plural(scanned, 'escaneado', 'escaneados')}`;
    }
    const anyScanned = asNumber(fields.filings_scanned);
    // Sin número fiable no se sabe el plural: se conserva el texto anterior.
    return anyScanned !== null
        ? plural(anyScanned, 'analizado', 'analizados')
        : `${countText(fields.filings_scanned)} analizados`;
}

/**
 * Copy de la lectura DURABLE (`GET /api/insider/filings`).
 *
 * Esa lectura no va a EDGAR: consulta la tabla de filings ya persistidos por el
 * monitor. Si falla, el `count` que llega es 0 con `status` distinto de `ok`,
 * así que ese 0 no es un recuento sino un «no se pudo leer». Decirlo es lo que
 * separa un fallo de lectura de «no hay Form 4 guardados»; y decir por qué
 * importa lo segundo: las señales de arriba se leen de SEC EDGAR directamente y
 * no dependen de ese histórico.
 */
export function durableReadCopy(fields: InsiderStatusFields, locale: Locale = 'es'): {
    header: string;
    detail: string | null;
} {
    const header = locale === 'en' ? tEn()('insider.statusCopy.durableReadFailed') :
        'No se ha podido leer el histórico de filings guardados por el monitor, así que su número es ' +
        'desconocido y no cero: es un fallo de esa lectura, no una ausencia de Form 4. Las señales de ' +
        'arriba se leen de SEC EDGAR directamente y no dependen de ese histórico.';
    const detail = typeof fields.reason === 'string' && fields.reason ? fields.reason : null;
    return { header, detail };
}

/**
 * Etiqueta de procedencia cuando la lectura live de EDGAR falló y las señales
 * salen de filings ya persistidos (Form 4/4-A inmutables). Sin esta línea el
 * usuario creería que la lectura live funcionó. Devuelve null si ningún filing
 * vino de la copia persistida.
 */
export function persistedSourceCopy(
    ticker: string,
    fields: InsiderStatusFields,
    countText: CountText,
    locale: Locale = 'es',
): string | null {
    const fromPersisted = asNumber(fields.filings_from_persisted);
    if (fromPersisted === null || fromPersisted <= 0) return null;
    const scanned = asNumber(fields.filings_scanned);
    if (locale === 'en') {
        const latestEn = typeof fields.latest_persisted_filing_date === 'string' && fields.latest_persisted_filing_date
            ? fields.latest_persisted_filing_date : tEn()('insider.statusCopy.noDate');
        return scanned !== null
            ? tEn()('insider.statusCopy.persistedOf', { ticker, count: countText(fromPersisted), scanned: countText(scanned), latest: latestEn })
            : tEn()('insider.statusCopy.persisted', { ticker, count: countText(fromPersisted), latest: latestEn });
    }
    const latest =
        typeof fields.latest_persisted_filing_date === 'string' && fields.latest_persisted_filing_date
            ? fields.latest_persisted_filing_date
            : 's/d';
    const of = scanned !== null ? ` de ${countText(scanned)}` : '';
    return `${ticker}: ${countText(fromPersisted)}${of} Form 4 desde filings persistidos (último filing: ${latest}); la lectura en vivo de SEC EDGAR falló. Los datos son los de esos filings, no de hoy.`;
}
