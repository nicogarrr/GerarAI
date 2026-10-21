/**
 * Páginas de cotización (landings) que la ingesta a veces indexa como si
 * fueran noticias. Caso real (ficha HYMC, 21-oct-2026): «Precio de la
 * acción, noticias, cotización e historial de Hycroft Mining Holding
 * Corporation (HYMC)» — traducción del título de la página /quote/HYMC de
 * Yahoo Finance («…Stock Price, News, Quote & History») — colada en las
 * «5 noticias de mayor materialidad». Una landing NO es una noticia y no
 * puede presentarse como material.
 *
 * Detección estricta, nada fuzzy:
 * 1. URL con forma de página de cotización de Yahoo (/quote/...), en
 *    cualquier subdominio regional (sg., uk., ...). Los artículos de
 *    Yahoo viven en /news/ y NO se tocan.
 * 2. Si no hay URL, la plantilla EXACTA del titular original de esa
 *    página (verbatim ingerido, no traducciones).
 * La clasificación durable corresponde a la ingesta (backend); esto es la
 * barrera de presentación: ninguna superficie del frontend vende una
 * landing como noticia.
 */
export function isQuoteLandingEvent(event: { url?: string | null; title?: string | null; original_headline?: string | null }): boolean {
    const url = event.url?.trim().toLowerCase() ?? '';
    if (/^https?:\/\/([a-z-]+\.)*finance\.yahoo\.com\/quote\//.test(url)) return true;
    const headline = (event.original_headline ?? event.title ?? '').trim();
    return /\([A-Z0-9.]+\)\s+Stock Price, News, Quote (&|and) History/i.test(headline);
}
