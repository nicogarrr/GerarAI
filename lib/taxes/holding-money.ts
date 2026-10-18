// @ts-expect-error TS5097
import { formatMoney, NA } from '../format.ts';

/**
 * F311: los importes de «Posiciones Fiscales» llegaban crudos a la tabla
 * («3589.265983») porque RecordList renderiza con String(value). Las tres
 * columnas monetarias se formatean en es-ES con la divisa de la PROPIA fila
 * (una cartera puede mezclar EUR y USD); sin divisa válida se asume EUR,
 * que es la base del informe fiscal.
 */
export const TAX_HOLDING_MONEY_COLUMNS = ['cost_basis', 'market_value', 'unrealized_pnl'] as const;

export function formatHoldingMoney(value: unknown, currency: unknown): string {
    if (value === null || value === undefined || value === '') return NA;
    const cur = typeof currency === 'string' && /^[A-Za-z]{3}$/.test(currency.trim())
        ? currency.trim().toUpperCase()
        : 'EUR';
    return formatMoney(value as number | string, cur);
}

/**
 * Una posicion con cantidad > 0 y base de coste 0 (o ausente) NO tiene coste
 * conocido: el 0 es ausencia de dato, no un coste real. Mismo criterio que el
 * resumen de cartera (cost > 0). Base de coste y plusvalia latente (market_value
 * menos esa base) se muestran N/D; el valor de mercado no depende de la base.
 */
export function formatHoldingCell(
    column: (typeof TAX_HOLDING_MONEY_COLUMNS)[number],
    value: unknown,
    record: { quantity?: unknown; cost_basis?: unknown; currency?: unknown },
): string {
    if (column === 'cost_basis' || column === 'unrealized_pnl') {
        const quantity = Number(record.quantity);
        const cost = record.cost_basis === null || record.cost_basis === undefined || record.cost_basis === ''
            ? null
            : Number(record.cost_basis);
        const costUnknown = cost === null || Number.isNaN(cost) || (cost === 0 && quantity > 0);
        if (costUnknown) return NA;
    }
    return formatHoldingMoney(value, record.currency);
}
