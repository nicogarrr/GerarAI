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

export function onePerIssuer<T extends SearchRow>(rows: T[], query = ''): T[] {
    const suffixed = rows.filter((r) => r.symbol.includes('.'));
    const q = query.trim().toUpperCase();
    // Ticker exacto escrito por el usuario (KO, ASTS): gana el listado desnudo
    // y se ocultan los listados con sufijo del mismo emisor (KO.MX, KO.VI).
    const exactBare = q && !q.includes('.') ? rows.find((r) => r.symbol.toUpperCase() === q) : undefined;
    const exactToken = exactBare ? firstNameToken(exactBare.description) : '';
    return rows.filter((row) => {
        if (exactBare) {
            if (row === exactBare) return true;
            if (
                row.symbol.includes('.') &&
                row.symbol.toUpperCase().startsWith(`${q}.`) &&
                exactToken &&
                firstNameToken(row.description) === exactToken
            ) {
                return false;
            }
        }
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
