/**
 * Resumen a pintar bajo un titular. Devuelve null si el resumen solo repite el
 * titular (igual o empezando por él sin añadir nada); si lo repite y añade
 * texto, quita el titular del inicio (y capitaliza: el texto que queda debe
 * leerse en español natural, no como continuación pegada). Un resumen cortado
 * a media palabra se recorta a la última palabra completa con puntos
 * suspensivos.
 *
 * Higiene de fragmentos (medido en prod, 19-oct-2026: 18/30 resúmenes eran
 * fragmentos feos o basura — «News TradingView», «treet», «Wall Street»,
 * restos a media frase): no se pinta un resumen que
 *   - es un trozo del propio titular (subcadena normalizada), o
 *   - no cierra con puntuación y es demasiado corto o empieza por una
 *     palabra función («Of Tesla — Sees Announcement…»), o
 *   - llega ya cortado de origen (termina en «…»/«...»), empieza a media
 *     narración («Told a very different story.…») o es demasiado corto para
 *     aportar aunque cierre con punto («Million children.»). Medido en prod
 *     19-oct-2026: los 4 resúmenes que sobrevivían eran de estos tipos.
 * Las cabeceras de agencia («Dublin, Oct. 19, 2026 (GLOBE NEWSWIRE) -- …») se
 * recortan al pintar y lo que queda vuelve a pasar la higiene.
 * Lo que sí se pinta se capitaliza y, si no cierra, termina en «…» (display;
 * el original guardado no se toca). Mejor sin resumen que un fragmento roto.
 */

const norm = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();

const FUNCTION_WORDS = new Set([
    'of', 'to', 'in', 'on', 'for', 'with', 'as', 'at', 'by', 'from', 'and', 'but', 'or',
    'de', 'del', 'la', 'el', 'los', 'las', 'en', 'con', 'por', 'para', 'y', 'o', 'que', 'se', 'su',
]);

const TERMINAL_PUNCT = /[.!?…"”)\]]$/;

function escapeRegExp(value: string): string {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Sufijo « - Fuente» o « Fuente» pegado al final por el proveedor: la fuente
 *  ya se pinta en su propio campo; al pintar se recorta solo cuando coincide. */
function stripSourceSuffix(text: string, source: string | null | undefined): string {
    const src = source?.trim();
    if (!src) return text;
    const suffix = new RegExp(`\\s*[-–—]?\\s*${escapeRegExp(src)}\\.?\\s*$`, 'i');
    return text.replace(suffix, '').trim();
}

function capitalizeFirst(text: string): string {
    const match = /[\p{L}]/u.exec(text);
    if (!match || match.index > 3) return text;
    const i = match.index;
    return text.slice(0, i) + text[i].toUpperCase() + text.slice(i + 1);
}

/** Cortado en origen: el proveedor ya lo entregó con puntos suspensivos. */
const TRUNCATED_AT_SOURCE = /(…|\.{3})\s*$/;

/** Arranque a media narración (resto de un scraping cortado). */
const CONTINUATION_START = /^(told|said|added|noted|reported|claimed|alleged|wrote|continued|dijo|contó|añadió|señaló)\b/i;

/** Arranque con unidad suelta: resto de una cifra cortada («…70 Million children.»). */
const UNIT_START = /^(million|billion|trillion|thousand|percent|percentage|millones|mil)\b/i;

/** Cabecera de agencia al inicio: «Dublin, Oct. 19, 2026 (GLOBE NEWSWIRE) -- ». */
const WIRE_DATELINE = /\((?:GLOBE NEWSWIRE|GlobeNewswire|PR Newswire|PRN|Business Wire|Businesswire|ACCESSWIRE|EIN Presswire)\)\s*[-–—]{1,2}\s*/i;

function stripWireDateline(text: string): string {
    const match = WIRE_DATELINE.exec(text);
    if (match && match.index < 60) return text.slice(match.index + match[0].length).trim();
    return text;
}

function looksLikeFragment(text: string): boolean {
    const trimmed = text.trim();
    if (!trimmed) return true;
    if (TRUNCATED_AT_SOURCE.test(trimmed)) return true;
    const words = trimmed.split(/\s+/);
    if (CONTINUATION_START.test(trimmed) || UNIT_START.test(trimmed)) return true;
    if (TERMINAL_PUNCT.test(trimmed)) return false;
    if (words.length < 6) return true;
    return FUNCTION_WORDS.has(norm(words[0]));
}

export function newsSummaryToShow(headline: string, summary: string | null | undefined, source?: string | null): string | null {
    const text = (summary ?? '').replace(/\s+/g, ' ').trim();
    if (!text) return null;
    const h = norm(headline);
    const t = norm(text);
    if (!t || t === h) return null;
    let out = text;
    if (h && t.startsWith(h)) {
        const idx = out.toLowerCase().indexOf(headline.trim().toLowerCase());
        if (idx === 0) {
            const cutAt = headline.trim().length;
            // Titulares antiguos recortados a media palabra en la ingesta: si el
            // corte cae dentro de una palabra, el resto empieza con un fragmento
            // («…del Bernstein» + «nstein …») y se descarta la palabra partida.
            const wordChar = /[\p{L}\p{N}]/u;
            const midWord = wordChar.test(out.charAt(cutAt - 1)) && wordChar.test(out.charAt(cutAt));
            out = out.slice(cutAt).replace(/^[\s:.\-–,]+/, '');
            if (midWord) out = out.replace(/^\S+\s+/, '');
        } else return null;
        if (!out) return null;
    }
    out = stripSourceSuffix(out, source);
    out = stripWireDateline(out);
    if (!out) return null;
    // Trozo del propio titular (p. ej. la cola del titular de otro agregador
    // guardada como resumen): no aporta nada bajo el titular.
    if (h && h.includes(norm(out))) return null;
    if (looksLikeFragment(out)) return null;
    out = capitalizeFirst(out);
    if (!TERMINAL_PUNCT.test(out)) {
        if (out.length >= 150) {
            const cut = out.lastIndexOf(' ');
            if (cut > 0) out = out.slice(0, cut).replace(/[,;:\s]+$/, '');
        }
        out = out.replace(/[,;:\s]+$/, '') + '…';
    }
    return out;
}
