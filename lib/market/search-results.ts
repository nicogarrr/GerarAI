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

// Mercados con suficiente liquidez para ir antes que el resto de sufijos.
const LIQUID_SUFFIXES = new Set(['MC', 'L', 'PA', 'AS', 'DE', 'MI', 'SW', 'TO', 'HK', 'T', 'AX']);

function marketRank(r: SearchRow): number {
    const sym = r.symbol.toUpperCase();
    const idx = sym.lastIndexOf('.');
    if (idx < 0) return 0; // listado desnudo (EE. UU.)
    return LIQUID_SUFFIXES.has(sym.slice(idx + 1)) ? 1 : 2;
}

/**
 * Orden por mercado: EE. UU. primero, luego bolsas líquidas, luego el resto.
 * Una coincidencia exacta con lo escrito (query) conserva el primer puesto y
 * el orden de Finnhub se mantiene dentro de cada grupo (CPT: Camden antes que CPT.BK).
 */
export function marketPriority<T extends SearchRow>(rows: T[], query: string): T[] {
    const q = query.trim().toUpperCase();
    const exact = (r: T) => !!q && (r.symbol.toUpperCase() === q || (r.displaySymbol ?? '').toUpperCase() === q);
    const rest = rows.filter((r) => !exact(r));
    const ranked = rest
        .map((r, i) => ({ r, i, k: marketRank(r) }))
        .sort((a, b) => a.k - b.k || a.i - b.i)
        .map((x) => x.r);
    return [...rows.filter(exact), ...ranked];
}
