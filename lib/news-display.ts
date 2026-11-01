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
    originalHeadline?: string | null,
): string {
    return stripTickerPrefix(
        dedupeRepeatedHeadline(untokenizeHeadline(sourceHeadlineWithoutAddedTicker(title, ticker, headlineFromSource, originalHeadline))),
        ticker,
        headlineFromSource,
    );
}

/**
 * La ingesta antepone el ticker al texto guardado (F175). Si el titular
 * original de la fuente ya está persistido y el título guardado es exactamente
 * «TICKER » + ese original, se pinta el original: es el verbatim de la fuente y
 * evita repetir el ticker (ya visible en su columna). Un titular que de origen
 * empieza por el ticker no cumple la condición y se respeta.
 */
function sourceHeadlineWithoutAddedTicker(
    title: string,
    ticker: string | null | undefined,
    headlineFromSource: boolean | null | undefined,
    originalHeadline: string | null | undefined,
): string {
    const original = originalHeadline?.trim();
    const normalizedTicker = ticker?.trim().toUpperCase();
    if (headlineFromSource === false || !original || !normalizedTicker) return title;
    const trimmed = title.trimStart();
    if (!trimmed.toUpperCase().startsWith(`${normalizedTicker} `)) return title;
    const rest = trimmed.slice(normalizedTicker.length + 1);
    return rest.toLowerCase().startsWith(original.toLowerCase()) ? original : title;
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

/** Una noticia con la traducción atribuida cacheada por GerarAI (la que
 *  NewsHeadline pide al backend cuando el titular entra en pantalla). */
export type NewsDedupeEvent = {
    title?: string | null;
    url?: string | null;
    original_headline?: string | null;
    headline_translation?: { text?: string | null } | null;
};

function headlineKey(value: string | null | undefined): string {
    return (value ?? '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, ' ')
        .trim();
}

/** Claves de deduplicación de una noticia (identidad, nunca similitud):
 *  - `t:` título, titular original de la fuente y traducción española
 *    atribuida cacheada, todos normalizados (sin mayúsculas, tildes ni
 *    puntuación). La traducción comparte el espacio `t:` porque es la
 *    traducción atribuida de ESE evento: si coincide exactamente con el
 *    titular de otro evento, ambos son la misma historia en dos idiomas
 *    (pares ES/EN del mismo medio, QA ASTS 21-oct-2026). Solo la igualdad
 *    exacta agrupa; textos parecidos sin coincidir no se juntan.
 *  - `u:` URL sin parámetros. */
export function newsDedupeKeys(event: NewsDedupeEvent): string[] {
    const keys: string[] = [];
    for (const value of [event.title, event.original_headline, event.headline_translation?.text]) {
        const title = headlineKey(value);
        if (title) keys.push(`t:${title}`);
    }
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

/** Quita noticias repetidas por identidad (ver newsDedupeKeys), conservando
 *  la primera aparición: el orden de entrada decide cuál sobrevive (la ficha
 *  la ordena por materialidad antes de deduplicar). Los originales absorbidos
 *  no se borran: solo se dejan de pintar en esta lista. */
export function dedupeNewsEvents<T extends NewsDedupeEvent>(events: T[]): T[] {
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

/**
 * Dedup del feed de Inicio (pedido de Nico 1-nov-2026: la app de referencia
 * enseñaba el mismo titular dos veces). Mismo criterio que dedupeNewsEvents
 * (titular normalizado o URL), sobre artículos Finnhub ({headline, url}).
 */
export function dedupeArticles<T extends { headline?: string | null; url?: string | null }>(items: T[]): T[] {
    return dedupeNewsEvents(items.map((item) => ({ item, title: item.headline ?? '', url: item.url ?? undefined }))).map(
        (row) => row.item,
    );
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


/** Legacy ingestion joined identical title and summary. Remove only exact
 * repeated whole headlines, never repeated words within a real headline. */
export function dedupeRepeatedHeadline(title: string): string {
    const words = title.trim().split(/\s+/);
    for (let size = 4; size <= words.length / 2; size++) {
        if (words.length % size !== 0) continue;
        const first = words.slice(0, size).join(' ');
        if (words.every((word, index) => word === words[index % size])) return first;
    }
    return title;
}
