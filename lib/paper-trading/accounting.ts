/**
 * Contabilidad de la demo manual: posiciones y saldos a partir del libro.
 * Contrato en lib/paper-trading/types.ts.
 *
 * Defensa en profundidad (las actions validan antes de grabar; aquí se
 * defiende el libro):
 * - El FIFO ordena por executedAt (estable), NUNCA por el orden del array
 *   ni por createdAt (índices descendentes romperían el FIFO).
 * - Sobreventa: se cierra solo lo que hay y se abona SOLO esa parte; el
 *   exceso no crea dinero y queda en `violations`.
 * - Sobregiro: una compra sin saldo en su divisa no se aplica; queda en
 *   `violations`. No existe modo sobregiro implícito.
 * - Las entradas inválidas (toFill devuelve null) no llegan aquí: las
 *   acciones las rechazan y quedan en el historial como rejected.
 *
 * Limitación declarada: NO se aplican acciones corporativas (splits,
 * dividendos, ampliaciones); una posición mantenida a través de una de
 * ellas queda descuadrada y se dice en la pantalla.
 */

import {
    instrumentKey,
    type AccountState,
    type Currency,
    type Fill,
    type FxConversion,
    type LedgerEntry,
    type PaperPosition,
// @ts-expect-error -- node --test (--experimental-strip-types) exige la extension
// .ts en runtime; tsc la prohibe (TS5097). Mismo patron que los guards.
} from './types.ts';

type Lot = { quantity: number; price: number };

const multiplierOf = (fill: Fill) => (fill.instrument.kind === 'opcion' ? fill.instrument.contract.multiplier : 1);

export function computeManualDemoAccount(
    starting: Record<Currency, number>,
    entries: LedgerEntry[]
): AccountState {
    // FIFO por executedAt; desempate por tiebreak estable (createdAt de la
    // fila) si viene; el índice SOLO ordena lecturas sin persistencia (tests).
    const ordered = entries
        .map((entry, index) => ({ entry, index }))
        .sort((a, b) =>
            a.entry.executedAt - b.entry.executedAt ||
            (a.entry.tiebreak ?? a.index) - (b.entry.tiebreak ?? b.index)
        );

    const cash: Record<Currency, number> = { ...starting };
    const lots = new Map<string, Lot[]>();
    const realized = new Map<string, number>();
    const violations: string[] = [];

    const applyFx = (fx: FxConversion) => {
        if (fx.from === fx.to) {
            // N1: convertir una divisa en sí misma crearía dinero.
            violations.push(`fx ${fx.clientOrderId}: divisa origen y destino iguales (${fx.from}); rechazada`);
            return;
        }
        if (!Number.isFinite(fx.amountFrom) || fx.amountFrom <= 0 || !Number.isFinite(fx.rate) || fx.rate <= 0) {
            violations.push(`fx ${fx.clientOrderId}: importe o tipo inválido`);
            return;
        }
        if (cash[fx.from] < fx.amountFrom) {
            violations.push(`fx ${fx.clientOrderId}: saldo ${fx.from} insuficiente (${cash[fx.from]} < ${fx.amountFrom})`);
            return;
        }
        cash[fx.from] -= fx.amountFrom;
        cash[fx.to] += fx.amountFrom * fx.rate;
    };

    const applyFill = (fill: Fill) => {
        // N2: el libro separa por divisa: comprar SAN en EUR y vender SAN en
        // USD NO se cruzan en el mismo FIFO.
        const key = `${fill.currency}|${instrumentKey(fill.instrument)}`;
        const mult = multiplierOf(fill);
        const queue = lots.get(key) ?? [];
        if (fill.side === 'buy') {
            const cost = fill.quantity * fill.price * mult + fill.fee;
            if (cash[fill.currency] < cost) {
                violations.push(
                    `compra ${fill.clientOrderId} (${key} x${fill.quantity}): saldo ${fill.currency} insuficiente (${cash[fill.currency]} < ${cost})`
                );
                return;
            }
            cash[fill.currency] -= cost;
            queue.push({ quantity: fill.quantity, price: fill.price });
            lots.set(key, queue);
        } else {
            const held = queue.reduce((acc, lot) => acc + lot.quantity, 0);
            // Sin fills parciales en fase 1: si no cubre la posición entera,
            // la orden NO se aplica (ni cash ni lotes) y queda registrada.
            if (held < fill.quantity) {
                violations.push(
                    `venta ${fill.clientOrderId} (${key}): pedida x${fill.quantity}, posición x${held}; orden rechazada entera, sin movimiento`
                );
                return;
            }
            const closing = fill.quantity;
            cash[fill.currency] += closing * fill.price * mult - fill.fee;
            let remaining = closing;
            let pnl = realized.get(key) ?? 0;
            while (remaining > 0 && queue.length > 0) {
                const lot = queue[0];
                const closed = Math.min(remaining, lot.quantity);
                pnl += closed * (fill.price - lot.price) * mult;
                lot.quantity -= closed;
                remaining -= closed;
                if (lot.quantity === 0) queue.shift();
            }
            realized.set(key, pnl);
        }
    };

    for (const { entry } of ordered) {
        if ('kind' in entry && entry.kind === 'fx') applyFx(entry);
        else applyFill(entry as Fill);
    }

    const positions: PaperPosition[] = [];
    const realizedByCurrency: Record<Currency, number> = { EUR: 0, USD: 0 };
    for (const [key, queue] of lots) {
        const quantity = queue.reduce((acc, lot) => acc + lot.quantity, 0);
        if (quantity <= 0) continue;
        const last = ordered.map((o) => o.entry).filter((e): e is Fill => !('kind' in e) || e.kind !== 'fx')
            .filter((f) => `${f.currency}|${instrumentKey(f.instrument)}` === key).at(-1);
        const cost = queue.reduce((acc, lot) => acc + lot.quantity * lot.price, 0);
        positions.push({
            instrumentKey: key.split('|').slice(1).join('|'),
            name: last?.instrument.name ?? key,
            kind: last?.instrument.kind ?? 'accion',
            currency: last?.currency ?? 'EUR',
            quantity,
            avgCost: cost / quantity,
            realizedPnl: realized.get(key) ?? 0,
        });
    }
    for (const [key, pnl] of realized) {
        const cur = (key.split('|')[0] as Currency) ?? 'EUR';
        realizedByCurrency[cur] += pnl;
    }
    positions.sort((a, b) => a.instrumentKey.localeCompare(b.instrumentKey));

    return { cashByCurrency: cash, realizedPnlByCurrency: realizedByCurrency, positions, violations };
}
