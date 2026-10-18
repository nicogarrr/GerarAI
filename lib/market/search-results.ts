/**
 * Un resultado por emisor en el buscador. Finnhub devuelve el ADR/listado
 * principal ("ASML", USD) y el listado base ("ASML.AS", EUR) del mismo emisor
 * como valores distintos, y ambos abren la misma ficha. Se conserva el
 * listado con sufijo de mercado y se oculta el simbolo desnudo SOLO si el
 * primer termino del nombre coincide (ALM Almonty vs ALM.MC Almirall no se
 * funden).
 */
export type SearchRow = { symbol: string; description?: string; displaySymbol?: string; type?: string };

function firstNameToken(description: string | undefined): string {
    return (description ?? '')
        .toUpperCase()
        .replace(/[^A-Z0-9 ]/g, ' ')
        .trim()
        .split(/\s+/)[0] ?? '';
}

export function onePerIssuer<T extends SearchRow>(rows: T[]): T[] {
    const suffixed = rows.filter((r) => r.symbol.includes('.'));
    return rows.filter((row) => {
        if (row.symbol.includes('.')) return true;
        const token = firstNameToken(row.description);
        if (!token) return true;
        return !suffixed.some(
            (other) =>
                other.symbol.toUpperCase().startsWith(`${row.symbol.toUpperCase()}.`) &&
                firstNameToken(other.description) === token,
        );
    });
}

/** Coincidencia exacta de simbolo primero (SAP SE antes que Saputo SAP.TO); el resto conserva el orden. */
export function exactSymbolFirst<T extends SearchRow>(rows: T[], query: string): T[] {
    const q = query.trim().toUpperCase();
    if (!q) return rows;
    const exact = (r: T) => r.symbol.toUpperCase() === q || (r.displaySymbol ?? '').toUpperCase() === q;
    return [...rows.filter(exact), ...rows.filter((r) => !exact(r))];
}
