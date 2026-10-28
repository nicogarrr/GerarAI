'use client';

import { useCallback, useEffect, useRef, useState, useTransition } from 'react';

import { Button } from '@/components/ui/button';
import { Panel } from '@/components/ui/panel';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { AccountSummary } from './AccountSummary';
import { FxTicket } from './FxTicket';
import { LedgerTable } from './LedgerTable';
import { OrderTicket } from './OrderTicket';
import { PositionsTable } from './PositionsTable';
import { formatMoney, formatCountEs } from '@/lib/format';
import { valuationMatches, type DemoValuation } from '@/lib/market/demo-valuation';
import type { DemoStateView, HistoryPageResult, HistoryRow, SubmitFill, SubmitFx } from './submit';

export type ManualDemoPanelProps = {
    /** Vista de la cuenta devuelta por la acción; null mientras no está conectada. */
    account: DemoStateView | null;
    /** Historial de órdenes (ejecutadas y rechazadas, append-only): PRIMERA página. */
    ledger: HistoryRow[];
    /** ¿Hay más historial tras la primera página y con qué cursor pedirlo? */
    historyHasMore?: boolean;
    historyNextBefore?: string | null;
    /** Pide la página siguiente del historial (cursor estable, sin offset). */
    loadMoreHistory?: (before: string) => Promise<HistoryPageResult>;
    submitFill: SubmitFill;
    submitFx: SubmitFx;
    /** Valoración inicial con cotizaciones reales (null = no disponible). */
    valuation?: DemoValuation | null;
    /** Epoch ms en que se consultaron las cotizaciones de `valuation`. */
    valuationAsOf?: number | null;
    /** Vuelve a consultar cotizaciones bajo demanda. El panel lo llama solo:
     *  cada 60 s con la pestaña visible y posiciones abiertas, y al pulsar el
     *  botón manual. */
    refreshValuation?: () => Promise<RefreshResult>;
};

export type RefreshResult =
    | { ok: true; valuation: DemoValuation; asOf: number; listingUnavailable: boolean; quoteFetchFailed: boolean; retryAfterSeconds: number | null }
    | { ok: false; error: string };

const ASOF_FORMAT = new Intl.DateTimeFormat('es-ES', { timeZone: 'Europe/Madrid', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });

/** Cadencia base del auto-refresco: 60 s, el patrón de sondeo ya usado por
 *  la app (LiveMarketsPanel). OJO: Mercados usa Yahoo y esta valoración usa
 *  Finnhub; la cuota del plan Finnhub NO está verificada, así que el diseño
 *  no depende de ella: solo cuenta con pestaña visible, 1 llamada por
 *  símbolo distinto por ciclo (tope 25, acción existente) y backoff
 *  exponencial ante fallos (también cubre reintentos del listado US, que un
 *  fallo no cachea). */
const VALUATION_REFRESH_MS = 60_000;
const MAX_REFRESH_BACKOFF_MS = 16 * 60_000;

function ValuationSummary({ valuation, asOf, onRefresh, pending, error }: {
    valuation: DemoValuation;
    asOf: number | null;
    onRefresh: (() => void) | null;
    pending: boolean;
    error: string | null;
}) {
    return (
        <div className="mb-3 space-y-2 rounded-lg border border-gray-800 bg-gray-900/40 p-3 text-sm text-gray-300">
            <p>
                Valoradas {valuation.coverage.valued} de {formatCountEs(valuation.coverage.total, 'posición', 'posiciones')} con cotización del proveedor.
                {valuation.totals.length > 0 ? ' Los totales suman solo las valoradas, por divisa:' : ' Sin totales: ninguna posición tiene cotización.'}
            </p>
            {valuation.totals.length > 0 ? (
                <ul className="space-y-0.5">
                    {valuation.totals.map((total) => (
                        <li key={total.currency}>
                            {total.currency}: valor {formatMoney(total.marketValue, total.currency)} · PyG no realizada{' '}
                            {formatMoney(total.unrealizedPnl, total.currency)}
                        </li>
                    ))}
                </ul>
            ) : null}
            <p className="text-xs text-gray-500">
                Las opciones no se valoran (no hay cotización de su prima). Solo se valora con Finnhub y con la divisa verificada en su listado; el resto sale N/D.
                Se actualiza aproximadamente cada minuto mientras esta pestaña está visible (si el proveedor falla, espera más a propósito). También puedes solicitar una actualización con el botón
                {asOf ? ` · consultado a las ${ASOF_FORMAT.format(new Date(asOf))} (hora de Madrid)` : ''}.
            </p>
            {error ? <p role="alert" className="text-xs text-amber-300">{error}</p> : null}
            {onRefresh ? (
                <Button type="button" variant="outline" size="sm" onClick={onRefresh} disabled={pending}>
                    {pending ? 'Consultando…' : 'Actualizar cotizaciones'}
                </Button>
            ) : null}
        </div>
    );
}

/**
 * Panel de la cuenta demo MANUAL (paper trading). Todo es presentacional por
 * props: quien renderiza decide de dónde salen el estado y las acciones.
 *
 * Es una demo de práctica con dinero ficticio: las operaciones se registran
 * con el precio que introduce el usuario (manual simulada). No hay motor de
 * órdenes límite ni conexión con un broker; el registro sigue siendo manual.
 * Lo único automático es la reconsulta de la valoración mostrada (cada 60 s
 * con la pestaña visible), nunca el precio de los fills.
 */
export function ManualDemoPanel({ account, ledger, submitFill, submitFx, valuation: initialValuation = null, valuationAsOf = null, refreshValuation, historyHasMore = false, historyNextBefore = null, loadMoreHistory }: ManualDemoPanelProps) {
    const wired = account !== null;
    const [valuation, setValuation] = useState<DemoValuation | null>(initialValuation);
    const [asOf, setAsOf] = useState<number | null>(valuationAsOf);
    const [refreshError, setRefreshError] = useState<string | null>(null);
    const [pending, startTransition] = useTransition();
    // Paginación del historial: `ledger` (prop) es la primera página; las
    // siguientes se acumulan aquí. Transición PROPIA (no comparte `pending`
    // con el refresco de cotizaciones): son consultas independientes.
    const [extraRows, setExtraRows] = useState<HistoryRow[]>([]);
    const [historyCursor, setHistoryCursor] = useState<string | null>(historyNextBefore);
    const [moreHistory, setMoreHistory] = useState(historyHasMore);
    const [loadMoreError, setLoadMoreError] = useState<string | null>(null);
    const [loadingMore, startLoadMore] = useTransition();
    // Un refresh del servidor (fill, rechazo, F5) trae una PRIMERA página
    // nueva en `ledger`: se descartan las extra acumuladas (siguen pudiendo
    // cargarse con el botón) para no mezclar filas de la foto anterior.
    // Ajuste DURANTE el render (patrón oficial de React para resetear estado
    // cuando cambia una prop), no un efecto: así nunca se pinta la mezcla.
    const [prevLedger, setPrevLedger] = useState(ledger);
    if (prevLedger !== ledger) {
        setPrevLedger(ledger);
        setExtraRows([]);
        setHistoryCursor(historyNextBefore);
        setMoreHistory(historyHasMore);
        setLoadMoreError(null);
    }
    const onLoadMoreHistory = () => {
        if (!loadMoreHistory || !historyCursor) return;
        const before = historyCursor;
        startLoadMore(async () => {
            setLoadMoreError(null);
            const result = await loadMoreHistory(before);
            if (!result.ok) {
                setLoadMoreError(result.message);
                return;
            }
            // Dedupe por clientOrderId (único por cuenta): si entre página y
            // página hubo refresh, una fila no puede aparecer dos veces.
            setExtraRows((prev) => {
                const seen = new Set([...ledger, ...prev].map((r) => r.clientOrderId));
                return [...prev, ...result.orders.filter((r) => !seen.has(r.clientOrderId))];
            });
            setMoreHistory(result.hasMore);
            setHistoryCursor(result.nextBefore);
        });
    };
    // Si cambian posiciones, cantidades o costes tras valorar, la valoracion
    // guardada ya no describe la cuenta: se oculta (nada de totales viejos
    // mezclados con filas nuevas) hasta pulsar el boton.
    const positions = account?.positions ?? [];
    const valuationIsCurrent = valuation !== null && valuationMatches(valuation, positions);
    const activeValuation = valuationIsCurrent ? valuation : null;
    // Candado COMPARTIDO entre el botón manual y el auto-refresco (ref:
    // solo se toca en handlers/efectos, no en render). Como nunca hay más de
    // una consulta en vuelo, ninguna respuesta vieja puede pisar el resultado
    // de una más nueva. `refreshing` es el busy real (manual u automático):
    // los botones se deshabilitan y muestran «Consultando…» mientras tanto,
    // así un clic durante una consulta no muere sin aviso.
    const refreshLock = useRef({ inFlight: false, failures: 0, lastStart: 0, holdUntil: 0 });
    const [refreshing, setRefreshing] = useState(false);
    const runRefresh = useCallback(async () => {
        if (!refreshValuation) return;
        const lock = refreshLock.current;
        if (lock.inFlight) return;
        lock.inFlight = true;
        lock.lastStart = Date.now();
        setRefreshing(true);
        try {
            const result = await refreshValuation();
            if (result.ok) {
                // Fallos transitorios con respuesta ok (filas N/D): listado
                // de divisas caído o TODAS las cotizaciones fallidas (429,
                // red, timeout). Cuestan fetch y no valoran nada: arman el
                // backoff. Un dato genuinamente ausente o viejo NO lo arma.
                lock.failures = result.listingUnavailable || result.quoteFetchFailed ? lock.failures + 1 : 0;
                // Retry-After expuesto por el proveedor: no reintentar antes.
                lock.holdUntil = result.retryAfterSeconds ? Date.now() + result.retryAfterSeconds * 1000 : 0;
                setValuation(result.valuation);
                setAsOf(result.asOf);
                setRefreshError(null);
            } else {
                lock.failures += 1;
                setRefreshError(`No se pudieron actualizar las cotizaciones: ${result.error}`);
            }
        } catch {
            lock.failures += 1;
            setRefreshError('No se pudieron actualizar las cotizaciones: fallo de red o del servidor.');
        } finally {
            lock.inFlight = false;
            setRefreshing(false);
        }
    }, [refreshValuation]);
    const onRefresh = () => {
        if (refreshValuation) startTransition(() => runRefresh());
    };
    const refreshBusy = pending || refreshing;

    // Auto-refresco de la valoración: una cotización servida envejece sola,
    // así que el panel la reconsulta periódicamente sin acción del usuario.
    // Puertas: pestaña visible, posiciones abiertas, candado compartido y
    // backoff exponencial tras fallos (60s×2^n, tope 16 min).
    // Al volver a la pestaña se repone si el último intento ya cumplió su
    // espera. Sin endpoint nuevo: reutiliza la acción de valoración.
    // La cadencia es APROXIMADA: el intervalo marca los ticks y due() mide
    // desde el inicio de la última consulta, así que el ritmo real es
    // 60-120 s según fase y duración del fetch, y mayor con backoff o
    // Retry-After. El copy lo dice («aproximadamente»): nada de prometer
    // una monitorización exacta.
    const hasPositions = positions.length > 0;
    useEffect(() => {
        if (!refreshValuation || !hasPositions) return;
        const due = () => {
            const lock = refreshLock.current;
            const wait = Math.min(VALUATION_REFRESH_MS * 2 ** lock.failures, MAX_REFRESH_BACKOFF_MS);
            return Date.now() - lock.lastStart >= wait && Date.now() >= lock.holdUntil;
        };
        const tick = () => {
            if (document.visibilityState !== 'visible' || !due()) return;
            void runRefresh();
        };
        const timer = window.setInterval(tick, VALUATION_REFRESH_MS);
        const onVisible = () => {
            if (document.visibilityState === 'visible' && due()) tick();
        };
        document.addEventListener('visibilitychange', onVisible);
        return () => {
            window.clearInterval(timer);
            document.removeEventListener('visibilitychange', onVisible);
        };
    }, [refreshValuation, hasPositions, runRefresh]);
    return (
        <div className="mt-6 space-y-6">
            <p className="rounded-lg border border-gray-800 bg-gray-900/40 p-3 text-sm text-gray-400">
                Cuenta de práctica con saldo ficticio. Registras operaciones con el precio que introduces tú:
                no es una ejecución de mercado ni hay conexión con un broker.
            </p>

            {account ? <AccountSummary account={account} /> : null}

            <Tabs defaultValue="operar">
                <TabsList className="h-auto min-h-[50px] w-full flex-wrap">
                    <TabsTrigger className="min-h-11" value="operar">Operar</TabsTrigger>
                    <TabsTrigger className="min-h-11" value="divisas">Divisas</TabsTrigger>
                    <TabsTrigger className="min-h-11" value="posiciones">Posiciones</TabsTrigger>
                    <TabsTrigger className="min-h-11" value="historial">Historial</TabsTrigger>
                </TabsList>
                <TabsContent value="operar" className="mt-4">
                    <Panel title="Registrar operación">
                        <OrderTicket submitFill={submitFill} disabled={!wired} />
                        {!wired ? (
                            <p className="mt-3 text-xs text-gray-500">
                                El registro en servidor todavía no está conectado; el formulario se activará
                                cuando lo esté.
                            </p>
                        ) : null}
                    </Panel>
                </TabsContent>
                <TabsContent value="divisas" className="mt-4">
                    <Panel title="Conversión EUR ⇄ USD">
                        <FxTicket submitFx={submitFx} disabled={!wired} />
                        {!wired ? (
                            <p className="mt-3 text-xs text-gray-500">
                                El registro en servidor todavía no está conectado; el formulario se activará
                                cuando lo esté.
                            </p>
                        ) : null}
                    </Panel>
                </TabsContent>
                <TabsContent value="posiciones" className="mt-4">
                    <Panel title="Posiciones abiertas">
                        {activeValuation ? (
                            <ValuationSummary valuation={activeValuation} asOf={asOf} onRefresh={refreshValuation ? onRefresh : null} pending={refreshBusy} error={refreshError} />
                        ) : refreshValuation && positions.length > 0 ? (
                            <div className="mb-3 space-y-2">
                                <p className="text-xs text-gray-500">
                                    {valuation
                                        ? 'Sin actualizar: las posiciones han cambiado desde la última consulta de cotizaciones. Se reconsultan solas con la pestaña visible, o puedes pedirlo con el botón.'
                                        : 'Valoración no disponible todavía: sin cotizaciones consultadas. Se consultan solas con la pestaña visible, o puedes pedirlo con el botón.'}
                                </p>
                                {refreshError ? <p role="alert" className="text-xs text-amber-300">{refreshError}</p> : null}
                                <Button type="button" variant="outline" size="sm" onClick={onRefresh} disabled={refreshBusy}>
                                    {refreshBusy ? 'Consultando…' : 'Consultar cotizaciones'}
                                </Button>
                            </div>
                        ) : null}
                        <PositionsTable positions={positions} valuation={activeValuation} />
                    </Panel>
                </TabsContent>
                <TabsContent value="historial" className="mt-4">
                    <Panel title="Historial de operaciones">
                        <LedgerTable entries={[...ledger, ...extraRows]} />
                        {loadMoreHistory && moreHistory ? (
                            <div className="mt-3">
                                <Button type="button" variant="outline" size="sm" onClick={onLoadMoreHistory} disabled={loadingMore}>
                                    {loadingMore ? 'Cargando…' : 'Cargar más'}
                                </Button>
                            </div>
                        ) : null}
                        {loadMoreError ? (
                            <p role="alert" className="mt-2 text-xs text-amber-300">
                                No se pudo cargar más historial: {loadMoreError}
                            </p>
                        ) : null}
                    </Panel>
                </TabsContent>
            </Tabs>
        </div>
    );
}
