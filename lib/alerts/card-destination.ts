/**
 * F300-extensión: destino principal de una tarjeta de alerta del inicio.
 * La tarjeta entera navega (enlace estirado) al destino más útil: la
 * investigación del ticker si lo hay; si no, el documento fuente. Sin
 * ninguno, la tarjeta no es navegable. El CTA secundario queda por encima
 * (z-10) y conserva su propio destino.
 */
export type AlertCardDestination = { href: string; external: boolean };

/** Una alerta puede traer varias clases de acciones ("LEN, LEN.B"): la ficha usa solo la primera. */
export function alertPrimaryTicker(ticker: string): string {
    return ticker.split(/[,\s]+/).filter(Boolean)[0] ?? ticker;
}

/** Destino de "Revisar tesis": nunca un ticker con coma o espacio (daba 404). */
export function alertThesisHref(ticker: string): string {
    return `/research/${encodeURIComponent(alertPrimaryTicker(ticker))}?view=thesis`;
}

export function alertCardDestination(item: {
    ticker?: string | null;
    sourceUrl?: string | null;
}): AlertCardDestination | null {
    if (item.ticker) {
        // Mismo destino que el CTA visible: la vista de tesis de la ficha.
        // La copia promete tesis; mandar al overview seria un destino desalineado.
        return { href: alertThesisHref(item.ticker), external: false };
    }
    if (item.sourceUrl) {
        return { href: item.sourceUrl, external: true };
    }
    return null;
}
