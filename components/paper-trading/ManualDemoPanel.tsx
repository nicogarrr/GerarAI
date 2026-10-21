'use client';

import { Panel } from '@/components/ui/panel';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { AccountState, LedgerEntry } from '@/lib/paper-trading/types';
import { AccountSummary } from './AccountSummary';
import { FxTicket } from './FxTicket';
import { LedgerTable } from './LedgerTable';
import { OrderTicket } from './OrderTicket';
import { PositionsTable } from './PositionsTable';
import type { SubmitFill, SubmitFx } from './submit';

export type ManualDemoPanelProps = {
    /** Estado recalculado en servidor; null mientras la cuenta no está conectada. */
    account: AccountState | null;
    /** Operaciones ejecutadas registradas (append-only). */
    ledger: LedgerEntry[];
    submitFill: SubmitFill;
    submitFx: SubmitFx;
};

/**
 * Panel de la cuenta demo MANUAL (paper trading). Todo es presentacional por
 * props: quien renderiza decide de dónde salen el estado y las acciones.
 *
 * Es una demo de práctica con dinero ficticio: las operaciones se registran
 * con el precio que introduce el usuario (manual simulada). No hay feed
 * automático, ni motor de órdenes límite, ni conexión con un broker.
 */
export function ManualDemoPanel({ account, ledger, submitFill, submitFx }: ManualDemoPanelProps) {
    const wired = account !== null;
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
                        <PositionsTable positions={account?.positions ?? []} />
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
