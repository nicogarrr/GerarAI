'use client';

import { useCallback, useEffect, useState, useTransition } from 'react';

import { Button } from '@/components/ui/button';
import { Panel } from '@/components/ui/panel';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { AccountSummary } from './AccountSummary';
import { FxTicket } from './FxTicket';
import { LedgerTable } from './LedgerTable';
import { OrderTicket } from './OrderTicket';
import { PositionsTable } from './PositionsTable';
import { formatMoney } from '@/lib/format';
import { valuationMatches, type DemoValuation } from '@/lib/market/demo-valuation';
import type { DemoStateView, HistoryRow, SubmitFill, SubmitFx } from './submit';

export type ManualDemoPanelProps = {
    /** Vista de la cuenta devuelta por la acción; null mientras no está conectada. */
    account: DemoStateView | null;
    /** Historial de órdenes (ejecutadas y rechazadas, append-only). */
    ledger: HistoryRow[];
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

export type RefreshResult = { ok: true; valuation: DemoValuation; asOf: number } | { ok: false; error: string };

const ASOF_FORMAT = new Intl.DateTimeFormat('es-ES', { timeZone: 'Europe/Madrid', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });

/** Cadencia del auto-refresco de la valoración: la misma que Mercados
 *  (LiveMarketsPanel), patrón ya asumido de la app para cotizaciones del
 *  mismo proveedor. Sin endpoint nuevo: cada ciclo reutiliza la acción de
 *  valoración existente (1 llamada Finnhub por símbolo distinto, tope 25). */
const VALUATION_REFRESH_MS = 60_000;

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
                Valoradas {valuation.coverage.valued} de {valuation.coverage.total} posiciones con cotización del proveedor.
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
                Se actualiza cada minuto mientras esta pestaña está visible; el botón la refresca al momento
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
export function ManualDemoPanel({ account, ledger, submitFill, submitFx, valuation: initialValuation = null, valuationAsOf = null, refreshValuation }: ManualDemoPanelProps) {
    const wired = account !== null;
    const [valuation, setValuation] = useState<DemoValuation | null>(initialValuation);
    const [asOf, setAsOf] = useState<number | null>(valuationAsOf);
    const [refreshError, setRefreshError] = useState<string | null>(null);
    const [pending, startTransition] = useTransition();
    // Si cambian posiciones, cantidades o costes tras valorar, la valoracion
    // guardada ya no describe la cuenta: se oculta (nada de totales viejos
    // mezclados con filas nuevas) hasta pulsar el boton.
    const positions = account?.positions ?? [];
    const valuationIsCurrent = valuation !== null && valuationMatches(valuation, positions);
    const activeValuation = valuationIsCurrent ? valuation : null;
    const runRefresh = useCallback(async () => {
        if (!refreshValuation) return;
        const result = await refreshValuation();
        if (result.ok) {
            setValuation(result.valuation);
            setAsOf(result.asOf);
            setRefreshError(null);
        } else {
            setRefreshError(`No se pudieron actualizar las cotizaciones: ${result.error}`);
        }
    }, [refreshValuation]);
    const onRefresh = refreshValuation ? () => startTransition(() => runRefresh()) : null;

    // Auto-refresco de la valoración (pedido de Nico, 21-oct-2026: «No se
    // actualiza sola»). Puertas: pestaña visible, posiciones abiertas y sin
    // consulta en vuelo (nada de fanout invisible ni solapes). Al volver a la
    // pestaña se repone si el último intento tiene más de un ciclo. Los
    // contadores son locales del efecto (patrón CompanyHeaderQuote): no son
    // estado de render.
    const hasPositions = positions.length > 0;
    useEffect(() => {
        if (!refreshValuation || !hasPositions) return;
        let inFlight = false;
        let lastAttempt = 0;
        const tick = () => {
            if (document.visibilityState !== 'visible' || inFlight) return;
            inFlight = true;
            lastAttempt = Date.now();
            void runRefresh().finally(() => {
                inFlight = false;
            });
        };
        const timer = window.setInterval(tick, VALUATION_REFRESH_MS);
        const onVisible = () => {
            if (document.visibilityState === 'visible' && Date.now() - lastAttempt >= VALUATION_REFRESH_MS) tick();
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
                <TabsList>
                    <TabsTrigger value="operar">Operar</TabsTrigger>
                    <TabsTrigger value="divisas">Divisas</TabsTrigger>
                    <TabsTrigger value="posiciones">Posiciones</TabsTrigger>
                    <TabsTrigger value="historial">Historial</TabsTrigger>
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
                            <ValuationSummary valuation={activeValuation} asOf={asOf} onRefresh={onRefresh} pending={pending} error={refreshError} />
                        ) : onRefresh && positions.length > 0 ? (
                            <div className="mb-3 space-y-2">
                                <p className="text-xs text-gray-500">
                                    {valuation
                                        ? 'Sin actualizar: las posiciones han cambiado desde la última consulta de cotizaciones. Se reconsultan solas en el próximo minuto con la pestaña visible, o ahora con el botón.'
                                        : 'Valoración no disponible todavía: sin cotizaciones consultadas. Se consultan solas en el próximo minuto con la pestaña visible, o ahora con el botón.'}
                                </p>
                                {refreshError ? <p role="alert" className="text-xs text-amber-300">{refreshError}</p> : null}
                                <Button type="button" variant="outline" size="sm" onClick={onRefresh} disabled={pending}>
                                    {pending ? 'Consultando…' : 'Consultar cotizaciones'}
                                </Button>
                            </div>
                        ) : null}
                        <PositionsTable positions={positions} valuation={activeValuation} />
                    </Panel>
                </TabsContent>
                <TabsContent value="historial" className="mt-4">
                    <Panel title="Historial de operaciones">
                        <LedgerTable entries={ledger} />
                    </Panel>
                </TabsContent>
            </Tabs>
        </div>
    );
}
