const norm = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();

/**
 * Resumen a pintar bajo un titular. Devuelve null si el resumen solo repite el
 * titular (igual o empezando por él sin añadir nada); si lo repite y añade
 * texto, quita el titular del inicio. Un resumen cortado a media palabra se
 * recorta a la última palabra completa y lleva puntos suspensivos.
 */
export function newsSummaryToShow(headline: string, summary: string | null | undefined): string | null {
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
    if (!/[.!?…"”)\]]$/.test(out) && out.length >= 150) {
        const cut = out.lastIndexOf(' ');
        if (cut > 0) out = `${out.slice(0, cut).replace(/[,;:\s]+$/, '')}…`;
    }
    return out;
}
