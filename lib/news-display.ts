/**
 * Representación del titular de noticias (quick win UX 4): los titulares
 * de display generados por GerarAI (metadata.headline_from_source ===
 * false, p.ej. «AAPL 8-K presentado ante la SEC») llevan el ticker como
 * prefijo legado F175; cuando la superficie ya muestra el ticker en su
 * propia columna/campo, el prefijo se omite para no pintarlo dos veces.
 * NUNCA se recorta un titular real de la fuente (verbatim), aunque
 * empiece por el ticker: ahí el texto es de la fuente y se respeta.
 */

/**
 * Devuelve el título a pintar junto a un ticker visible aparte.
 * Solo recorta el prefijo «TICKER » cuando headlineFromSource === false
 * (flag persistido en metadata por la ingesta / el script de saneado).
 */
export function newsDisplayTitle(
    title: string,
    ticker: string | null | undefined,
    headlineFromSource: boolean | null | undefined,
): string {
    return stripTickerPrefix(untokenizeHeadline(title), ticker, headlineFromSource);
}

/**
 * Algunos titulares llegan de la fuente (GDELT) tokenizados con espacios
 * alrededor de la puntuación: «AST SpaceMobile , Inc . ( ASTS )». Solo al
 * PINTAR se recoloca la puntuación («AST SpaceMobile, Inc. (ASTS)»); el texto
 * guardado sigue siendo el verbatim de la fuente (procedencia).
 */
export function untokenizeHeadline(title: string): string {
    return title
        .replace(/\s+([,.;:!?])(?=\s|$)/g, '$1')
        .replace(/\(\s+/g, '(')
        .replace(/\s+\)/g, ')')
        .replace(/[ \t]{2,}/g, ' ');
}

function stripTickerPrefix(
    title: string,
    ticker: string | null | undefined,
    headlineFromSource: boolean | null | undefined,
): string {
    if (headlineFromSource !== false || !ticker) return title;
    const normalizedTicker = ticker.trim().toUpperCase();
    if (!normalizedTicker) return title;
    const trimmed = title.trimStart();
    if (!trimmed.toUpperCase().startsWith(`${normalizedTicker} `)) return title;
    return trimmed.slice(normalizedTicker.length + 1);
}

/** Claves de deduplicación de una noticia: título normalizado (sin mayúsculas,
 *  tildes ni puntuación) y URL sin parámetros. */
export function newsDedupeKeys(event: { title?: string | null; url?: string | null }): string[] {
    const keys: string[] = [];
    const title = (event.title ?? '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, ' ')
        .trim();
    if (title) keys.push(`t:${title}`);
    if (event.url) {
        try {
            const parsed = new URL(event.url);
            keys.push(`u:${parsed.hostname.replace(/^www\./, '')}${parsed.pathname.replace(/\/+$/, '')}`);
        } catch {
            keys.push(`u:${event.url.trim()}`);
        }
    }
    return keys;
}

/** Quita noticias repetidas (mismo título normalizado o misma URL), conservando
 *  la primera aparición: el orden de entrada decide cuál sobrevive. */
export function dedupeNewsEvents<T extends { title?: string | null; url?: string | null }>(events: T[]): T[] {
    const seen = new Set<string>();
    const out: T[] = [];
    for (const event of events) {
        const keys = newsDedupeKeys(event);
        if (keys.some((key) => seen.has(key))) continue;
        keys.forEach((key) => seen.add(key));
        out.push(event);
    }
    return out;
}

function escapeRegExp(value: string): string {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Sufijo « - Fuente» pegado al titular por el proveedor (p.ej.
 * «... - Reuters»): la fuente ya se pinta en su propio campo, así que al
 * PINTAR se recorta solo cuando coincide con ella. El texto guardado no
 * se toca (procedencia).
 */
export function stripSourceSuffix(title: string, source: string | null | undefined): string {
    const src = source?.trim();
    if (!src) return title;
    const suffix = new RegExp(`\\s*[-–—]\\s*${escapeRegExp(src)}\\.?\\s*$`, 'i');
    return title.replace(suffix, '').trim();
}

/**
 * Ticker pegado delante del titular («ASTS: ...», «ASTS - ...», «(ASTS) ...»):
 * la tarjeta ya muestra el ticker en su insignia, así que al pintar se quita
 * el duplicado. Solo con separador explícito o paréntesis: un titular real
 * que empiece por una palabra igual al ticker sin separador se respeta.
 */
export function stripLeadingTicker(title: string, ticker: string | null | undefined): string {
    const t = ticker?.trim().toUpperCase();
    if (!t) return title;
    const parenthesized = new RegExp(`^\\(${escapeRegExp(t)}\\)\\s+`, 'i');
    const separated = new RegExp(`^${escapeRegExp(t)}\\s*[:·—–-]\\s+`, 'i');
    return title.replace(parenthesized, '').replace(separated, '').trim();
}
