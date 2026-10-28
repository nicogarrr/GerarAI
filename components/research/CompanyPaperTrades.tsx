import Link from 'next/link';

import { PaperThesisLine } from '@/components/proPicks/PaperProposalCard';
import { EmptyLink, EmptyState } from '@/components/ui/empty-state';
import { Panel } from '@/components/ui/panel';
import type { PaperTradeView } from '@/lib/actions/paper-trading.actions';

export const COMPANY_PAPER_LIMIT = 5;
const PAPER_HREF = '/propicks?tab=paper';
const STATUS: Record<string, string> = { pending: 'Pendiente de entrada', open: 'Abierta', closed: 'Cerrada' };

export type CompanyPaperState = { trades: PaperTradeView[]; error?: string } | null;

function amount(value: string | null | undefined, currency: string | null) {
    if (value === null || value === undefined || String(value).trim() === '') return null;
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return null;
    const sign = parsed > 0 ? '+' : '';
    return `${sign}${parsed.toLocaleString('es-ES', { maximumFractionDigits: 2 })} ${currency ?? ''}`.trim();
}

function day(value: string | null | undefined) {
    return value && Number.isFinite(Date.parse(value))
        ? new Date(value).toLocaleDateString('es-ES', { timeZone: 'Europe/Madrid' })
        : null;
}

function result(trade: PaperTradeView) {
    if (trade.status === 'pending') return 'Sin ejecutar: espera a que la cotización llegue a la entrada propuesta.';
    const closed = trade.status === 'closed';
    const gross = amount(closed ? trade.realized_pnl : trade.unrealized_pnl, trade.currency);
    const net = amount(closed ? trade.realized_pnl_net : trade.unrealized_pnl_net, trade.currency);
    if (!gross) return closed ? 'Resultado no disponible.' : 'Sin precio reciente: resultado abierto no disponible.';
    return `${closed ? 'Resultado' : 'Resultado abierto'} bruto ${gross}${net ? ` · neto ${net} (costes supuestos y dividendos)` : ' · neto N/D'}`;
}

/**
 * Operaciones simuladas del paper book para ESTA empresa, junto al diario de decisiones:
 * la hipótesis se contrasta donde vive la tesis, no en una pantalla aparte. Solo
 * lectura; el detalle completo y la calibración siguen en ProPicks.
 */
export function CompanyPaperTrades({ ticker, state }: { ticker: string; state: CompanyPaperState }) {
    const description = 'Operaciones simuladas sin capital real. Unas pocas no validan la tesis ni una estrategia.';
    if (state === null || state.error) {
        return <Panel description={description} id="paper-trading" title="Operaciones simuladas de esta empresa">
            <p className="text-sm text-amber-200" role="status">
                {state?.error ?? 'No se pudieron cargar las operaciones simuladas.'} No significa que no existan.
            </p>
        </Panel>;
    }
    // Un backend anterior al filtro por ticker devuelve todo el libro: nunca se mezclan empresas.
    const trades = state.trades.filter((trade) => trade.ticker.toUpperCase() === ticker.toUpperCase());
    if (trades.length === 0) {
        return <Panel description={description} id="paper-trading" title="Operaciones simuladas de esta empresa">
            <EmptyState
                action={<EmptyLink href={PAPER_HREF}>Ir a paper trading</EmptyLink>}
                description="Las propuestas simuladas se anclan a la tesis vigente al crearse."
                title="Sin operaciones simuladas para esta empresa."
            />
        </Panel>;
    }
    const visible = trades.slice(0, COMPANY_PAPER_LIMIT);
    return <Panel description={description} id="paper-trading" title="Operaciones simuladas de esta empresa">
        <ul aria-label={`Operaciones simuladas de ${ticker}`} className="divide-y divide-gray-800">
            {visible.map((trade) => {
                const created = day(trade.created_at);
                return <li className="space-y-1 py-3 first:pt-0 last:pb-0" key={trade.id}>
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <p className="text-sm font-medium text-gray-100">
                            {trade.direction === 'short' ? 'Corto' : 'Largo'} · {trade.horizon === 'five_years' ? 'tesis a 5 años' : 'operación a 30 días'}
                        </p>
                        <p className="text-xs text-gray-400">{STATUS[trade.status] ?? 'Estado no disponible'}{created ? ` · creada el ${created}` : ''}</p>
                    </div>
                    <p className="text-sm text-gray-300">{result(trade)}</p>
                    <PaperThesisLine trade={trade} />
                </li>;
            })}
        </ul>
        <p className="mt-4 text-xs text-gray-400">
            {trades.length > visible.length ? `Se muestran ${visible.length} de ${trades.length}. ` : ''}
            <Link className="text-teal-300 underline decoration-gray-700 underline-offset-4 hover:text-teal-200" href={PAPER_HREF}>
                Ver el detalle, los precios observados y la calibración
            </Link>
        </p>
    </Panel>;
}
