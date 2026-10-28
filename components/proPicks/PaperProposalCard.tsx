import type { PaperTradeView } from '@/lib/actions/paper-trading.actions';
import { formatCountEs } from '@/lib/format';

const stateLabel: Record<string, string> = { pending: 'Pendiente de entrada', open: 'Abierta', closed: 'Cerrada' };
const closeLabel: Record<string, string> = { stop: 'Límite de pérdidas', target: 'Objetivo', horizon: 'Fin del horizonte', manual: 'Cierre anticipado' };
const warningLabel: Record<string, string> = {
    split_cerrado_sin_ajustar: 'Split declarado durante la operación: el cierre no se reescribe y este resultado queda excluido de las estadísticas.',
    split_pendiente_sin_ajustar: 'Split declarado después de la propuesta: los niveles ya no son comparables y no se ejecuta.',
};
function number(value: string | number | null | undefined) {
    if (value === null || value === undefined || String(value).trim() === '') return 'Sin datos';
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed.toLocaleString('es-ES', { maximumFractionDigits: 6 }) : 'Sin datos';
}
function date(value: string | null | undefined) {
    if (!value || !Number.isFinite(Date.parse(value))) return 'Sin datos';
    return new Date(value).toLocaleString('es-ES', { timeZone: 'Europe/Madrid' });
}
function conviction(value: string) {
    const parsed = Number(value);
    return value.trim() && Number.isFinite(parsed) && parsed >= 0 && parsed <= 1 ? `${number(parsed * 100)} %` : 'Sin datos';
}

/** Qué tesis evaluaba la operación simulada; avisa si la tesis ha cambiado desde entonces. */
export function PaperThesisLine({ trade }: { trade: PaperTradeView }) {
    const anchor = trade.thesis_anchor;
    const thesisHref = `/research/${encodeURIComponent(trade.ticker)}?view=thesis`;
    if (!anchor) {
        return <p className="text-xs text-gray-400">
            {trade.thesis_version_id === undefined
                ? 'Tesis de referencia no disponible.'
                : 'Sin tesis anclada: no había tesis guardada al crear la propuesta o es anterior al anclaje.'}
        </p>;
    }
    return <p className="text-xs text-gray-400">
        Evaluaba la tesis v{anchor.version}{anchor.created_at ? ` del ${new Date(anchor.created_at).toLocaleDateString('es-ES', { timeZone: 'Europe/Madrid' })}` : ''}.{' '}
        {anchor.superseded
            ? <span className="text-amber-200">La tesis ha cambiado desde entonces (vigente: v{anchor.latest_version}); el resultado no valida la versión nueva.</span>
            : 'Sigue siendo la tesis vigente.'}{' '}
        <a className="text-teal-300 underline decoration-gray-700 underline-offset-4 hover:text-teal-200" href={thesisHref}>Ver tesis</a>
    </p>;
}

export function PaperProposalCard({ trade }: { trade: PaperTradeView }) {
    const direction = trade.direction === 'long' ? 'Largo' : trade.direction === 'short' ? 'Corto' : 'Sin dirección';
    const horizon = trade.horizon === 'five_years' ? 'Tesis 5 años' : trade.horizon === 'short' ? 'Operación a 30 días' : 'Sin horizonte';
    return <article className="min-w-0 space-y-4 rounded-lg border border-gray-700 p-4 text-sm text-gray-300" aria-label={`Propuesta simulada ${trade.ticker}`}>
        <div className="flex flex-wrap justify-between gap-2"><h3 className="font-semibold text-gray-100">{trade.ticker} · {direction} · {horizon}</h3><span>{stateLabel[trade.status] ?? 'Estado no disponible'}</span></div>
        <p className="text-xs text-gray-400">Operación simulada sin capital real. No es una orden al broker.</p>
        <section aria-label="Propuesta del modelo" className="space-y-2">
            <h4 className="font-medium text-teal-300">Propuesta del modelo · {trade.currency || 'Sin divisa'}</h4>
            <p className="break-words whitespace-pre-wrap">{trade.thesis || 'Tesis no disponible.'}</p>
            <dl className="grid min-w-0 grid-cols-2 gap-2 sm:grid-cols-4">
                <div><dt>Entrada propuesta</dt><dd>{number(trade.proposed_entry)}</dd></div>
                <div><dt>Límite de pérdidas propuesto</dt><dd>{number(trade.stop)}</dd></div>
                <div><dt>Objetivo propuesto</dt><dd>{number(trade.target)}</dd></div>
                <div><dt>Convicción del modelo</dt><dd>{conviction(trade.conviction)}</dd></div>
            </dl>
            <p className="text-xs text-gray-400">La convicción declarada no es una probabilidad de acierto validada. Los niveles son una propuesta, no precios de ejecución.</p>
            <p className="break-words whitespace-pre-wrap">Razonamiento: {trade.inference_basis || 'Sin datos'}</p>
            <PaperThesisLine trade={trade} />
            <p className="text-xs text-gray-400">Creada: {date(trade.created_at)} (hora de Madrid)</p>
        </section>
        <section aria-label="Precios observados" className="space-y-2 border-t border-gray-700 pt-3">
            <h4 className="font-medium text-gray-100">Precios observados · {trade.currency || 'Sin divisa'}</h4>
            <dl className="grid min-w-0 gap-2 sm:grid-cols-3">
                <div><dt>Entrada simulada</dt><dd>{number(trade.entry_price)}</dd><dd className="text-xs text-gray-400">{date(trade.entry_at)}</dd></div>
                <div><dt>Último precio registrado</dt><dd>{number(trade.mark_price)}</dd><dd className="text-xs text-gray-400">{date(trade.mark_at)}</dd></div>
                <div><dt>Cierre simulado</dt><dd>{number(trade.exit_price)}</dd><dd className="text-xs text-gray-400">{date(trade.exit_at)}</dd></div>
            </dl>
            <p className="break-words">Fuente de precios: {trade.price_source || 'Sin datos'} · Fechas en hora de Madrid.</p>
            <p>Cantidad simulada (supuesto): {number(trade.quantity)}</p>
            <p>Resultado bruto simulado: {number(trade.status === 'closed' ? trade.realized_pnl : trade.unrealized_pnl)} {trade.currency || ''}</p>
            <p>Resultado neto simulado (tras costes supuestos y dividendos): {number(trade.status === 'closed' ? trade.realized_pnl_net : trade.unrealized_pnl_net)} {trade.currency || ''}</p>
            {trade.cost_label === 'supuesto' && <p className="text-xs text-gray-400">Costes simulados (supuesto, no tarifa de broker): entrada {number(trade.entry_fee)} · salida {trade.status === 'closed' ? number(trade.exit_fee) : 'estimada al cierre'}.</p>}
            {(trade.dividends_count || trade.dividends_uncertain || trade.dividends_wrong_currency) ? <p className="text-xs text-gray-400">
                Dividendos devengados: {number(trade.dividends_total)} {trade.currency || ''} ({trade.dividends_count == null ? 'Eventos no disponibles' : formatCountEs(trade.dividends_count, 'evento', 'eventos')}{trade.dividends_source ? `, fuente: ${trade.dividends_source}` : ''}).
                {trade.dividends_uncertain ? ` ${trade.dividends_uncertain} evento(s) incierto(s) excluido(s).` : ''}
                {trade.dividends_wrong_currency ? ` ${trade.dividends_wrong_currency} en otra divisa ignorado(s), nunca convertidos.` : ''}
            </p> : null}
            {trade.split_adjustments ? <p className="text-xs text-gray-400">Ajustada por split: {trade.last_corporate_action || 'ajuste registrado'}.</p> : null}
            {trade.corporate_action_warning ? <p role="status" className="text-amber-200">{warningLabel[trade.corporate_action_warning] || `Acción corporativa registrada: ${trade.corporate_action_warning}`}</p> : null}
            {trade.status === 'closed' && <p>Motivo de cierre: {trade.close_reason ? closeLabel[trade.close_reason] || 'Otro motivo registrado' : 'Sin datos'}</p>}
        </section>
    </article>;
}
