/**
 * Contabilidad del paper trading: posiciones y cash a partir del libro
 * mayor de operaciones. FIFO (como el extracto de un broker) para el
 * coste medio y el P&L realizado.
 *
 * Limitacion declarada: NO se aplican acciones corporativas (splits,
 * dividendos, ampliaciones). Una posicion mantenida a traves de una de
 * ellas queda descuadrada respecto al mercado; es el precio de una demo
 * a coste 0 y se dice en la pantalla.
 */

export type PaperTradeInput = {
    symbol: string;
    side: 'buy' | 'sell';
    quantity: number;
    fillPrice: number;
};

export type PaperPosition = {
    symbol: string;
    quantity: number;
    /** Coste medio de las acciones vivas (FIFO). */
    avgCost: number;
    /** P&L realizado acumulado al vender (FIFO), en la moneda de la operacion. */
    realizedPnl: number;
};

export type PaperAccountState = {
    cash: number;
    realizedPnl: number;
    positions: PaperPosition[];
};

export function computePaperAccount(startingCash: number, trades: PaperTradeInput[]): PaperAccountState {
    const lots = new Map<string, { quantity: number; price: number }[]>();
    const realized = new Map<string, number>();
    let cash = startingCash;

    for (const trade of trades) {
        if (!Number.isFinite(trade.fillPrice) || trade.fillPrice <= 0) continue;
        if (!Number.isInteger(trade.quantity) || trade.quantity <= 0) continue;
        const symbol = trade.symbol.toUpperCase();
        if (trade.side === 'buy') {
            cash -= trade.quantity * trade.fillPrice;
            const queue = lots.get(symbol) ?? [];
            queue.push({ quantity: trade.quantity, price: trade.fillPrice });
            lots.set(symbol, queue);
        } else {
            cash += trade.quantity * trade.fillPrice;
            const queue = lots.get(symbol) ?? [];
            let remaining = trade.quantity;
            let pnl = realized.get(symbol) ?? 0;
            while (remaining > 0 && queue.length > 0) {
                const lot = queue[0];
                const closed = Math.min(remaining, lot.quantity);
                pnl += closed * (trade.fillPrice - lot.price);
                lot.quantity -= closed;
                remaining -= closed;
                if (lot.quantity === 0) queue.shift();
            }
            realized.set(symbol, pnl);
            // Si quedaba algo sin cubrir (vender mas de lo que se tenia,
            // solo posible con datos corruptos), se ignora el exceso: el
            // servidor valida antes de grabar, esto es defensa.
        }
    }

    const positions: PaperPosition[] = [];
    let realizedTotal = 0;
    for (const [symbol, queue] of lots) {
        realizedTotal += realized.get(symbol) ?? 0;
        const quantity = queue.reduce((acc, lot) => acc + lot.quantity, 0);
        if (quantity <= 0) continue;
        const cost = queue.reduce((acc, lot) => acc + lot.quantity * lot.price, 0);
        positions.push({ symbol, quantity, avgCost: cost / quantity, realizedPnl: realized.get(symbol) ?? 0 });
    }
    // Simbolos cerrados del todo tambien aportan su realizado.
    for (const [symbol, pnl] of realized) {
        if (!lots.has(symbol) || (lots.get(symbol) ?? []).length === 0) realizedTotal += 0; // ya sumado arriba si habia cola
        void symbol; void pnl;
    }
    positions.sort((a, b) => a.symbol.localeCompare(b.symbol));

    return { cash, realizedPnl: realizedTotal, positions };
}
