import type { Metadata } from 'next';
import { Building2, ExternalLink, FileText } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { EmptyState } from '@/components/ui/empty-state';
import BackendOffline from '@/components/system/BackendOffline';
import { SyncPortfoliosButton } from '../inversores/_components/SyncPortfoliosButton';
import {
    getManagerChanges,
    getManagerHoldings,
    getOwnershipManagers,
    type ManagerChanges,
    type ManagerHoldings,
} from '@/lib/actions/ownership.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { form13fValueToUsd } from '@/lib/form13f-value';
import { formatMarketCapUsd, formatDate, formatUserDateTime, formatNumber, NA } from '@/lib/format';
import { t } from '@/lib/i18n/t';

import SyncButton from './SyncButton';
import { ownershipManagerName } from '@/lib/ownership-display';
import { ownershipLimitations } from '@/lib/research/ownership-display';

const CHANGE_LABELS: Record<string, string> = {
    new: 'nueva posición',
    closed: 'cerrada',
    increased: 'aumentada',
    decreased: 'reducida',
    unchanged: 'sin cambios',
};

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
    title: 'Propiedad institucional (13F)',
    description:
        'Carteras de gestores institucionales tal como se declaran ante la SEC (Form 13F, EDGAR), con cambios trimestre a trimestre.',
};

/** El <value> del 13F va en dolares desde 2023 y en miles antes: se normaliza por
 *  la fecha del informe y se muestra el importe en USD. */
function formatValueUsd(raw: number | null, reportDate: string | null | undefined): string {
    const dollars = form13fValueToUsd(raw, reportDate);
    return dollars === null ? NA : formatMarketCapUsd(dollars);
}

function formatShares(shares: number | null): string {
    if (shares === null) return NA;
    return formatNumber(shares, { maximumFractionDigits: 0 });
}

/** Periodo 13F ("2026-06-30"): fecha en español; si el backend manda una
 *  etiqueta de trimestre, se muestra tal cual en vez de esconderla. */
function reportLabel(value: string | null | undefined): string {
    return value ? formatDate(value, { day: 'numeric', month: 'short', year: 'numeric' }, value) : NA;
}

type PageProps = {
    searchParams: Promise<{ cik?: string }>;
};

export default async function OwnershipPage({ searchParams }: PageProps) {
    const { cik: selectedCik } = await searchParams;
    const activeHref = selectedCik ? `/ownership?cik=${encodeURIComponent(selectedCik)}` : '/ownership';
    // La lista de gestores es la lectura esencial: sin ella la página no tiene
    // nada que mostrar. Antes su fallo se tragaba con `.catch(() => null)` y la
    // pantalla decía "no hay gestores (o el backend no responde)": dos estados
    // en un mismo texto, imposible de distinguir para el usuario.
    let managersResult: Awaited<ReturnType<typeof getOwnershipManagers>>;
    try {
        managersResult = await getOwnershipManagers();
    } catch (error) {
        if (isBackendUnavailableError(error)) {
            return <BackendOffline feature="Propiedad institucional (13F)" retryHref={activeHref} />;
        }
        throw error;
    }
    const managers = managersResult.managers;
    const limitations = managersResult.limitations;
    const activeCik = selectedCik ?? managers[0]?.cik ?? null;

    let holdings: ManagerHoldings | null = null;
    let changes: ManagerChanges | null = null;
    if (activeCik) {
        const [holdingsRead, changesRead] = await Promise.all([
            getManagerHoldings(activeCik).then(
                (value) => ({ value, error: null as unknown }),
                (error: unknown) => ({ value: null, error }),
            ),
            getManagerChanges(activeCik).then(
                (value) => ({ value, error: null as unknown }),
                (error: unknown) => ({ value: null, error }),
            ),
        ]);
        const readError = holdingsRead.error ?? changesRead.error;
        // Mismo backend para las tres lecturas: si alguna cae, el 13F entero no
        // es fiable y se dice, en vez de pintar tablas a medias como vacías.
        if (readError && isBackendUnavailableError(readError)) {
            return <BackendOffline feature="Propiedad institucional (13F)" retryHref={activeHref} />;
        }
        holdings = holdingsRead.value;
        changes = changesRead.value;
    }

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex w-full min-w-0 max-w-6xl flex-col gap-6 overflow-x-clip">
            <header className="flex flex-col gap-3 border-b border-gray-800 pb-5 lg:flex-row lg:items-end lg:justify-between">
                <div>
                    <p className="text-sm font-semibold uppercase text-teal-300">{t('ownership.title')}</p>
                    <h1 className="mt-1 text-3xl font-bold text-gray-100">Propiedad institucional (13F)</h1>
                    <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-400">
                        Posiciones declaradas ante la SEC. Los 13F pueden publicarse con hasta 45 días de retraso.
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <div className="flex items-center gap-2 rounded-lg border border-gray-800 bg-surface-1 px-3 py-2 text-sm text-gray-300">
                        <Building2 aria-hidden="true" className="h-4 w-4 text-teal-300" />
                        SEC 13F
                    </div>
                    <SyncButton />
                </div>
            </header>

            {limitations.length ? (
                <section className="rounded-xl border border-amber-900/60 bg-amber-950/20 p-4">
                    <h2 className="text-sm font-semibold text-amber-200">Límites de este dato</h2>
                    <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-gray-400">
                        {limitations.map((item) => <li key={item}>{ownershipLimitations(item)}</li>)}
                    </ul>
                </section>
            ) : null}

            {!managers.length ? (
                <EmptyState
                    description="La lista de gestores es una tabla revisada en código; se amplía de forma explícita en cada versión."
                    title="No hay gestores revisados en esta versión"
                />
            ) : (
                <section className="flex flex-wrap gap-2">
                    {managers.map((manager) => (
                        <a
                            className={`max-w-full rounded-lg border px-3 py-2 text-sm ${manager.cik === activeCik ? 'border-teal-700 bg-teal-950/30 text-teal-200' : 'border-gray-800 bg-surface-1 text-gray-300 hover:border-gray-700'}`}
                            href={`/ownership?cik=${manager.cik}`}
                            key={manager.cik}
                        >
                            {ownershipManagerName(manager.cik, manager.name)}
                            <span className="ml-2 text-xs text-gray-500">CIK {manager.cik}</span>
                        </a>
                    ))}
                </section>
            )}

            {activeCik && holdings ? (
                holdings.status === 'ok' ? (
                    <section className="rounded-xl border border-gray-800 bg-surface-1 p-5">
                        <div className="flex flex-col gap-2 md:flex-row md:items-center">
                            <h2 className="font-semibold text-gray-100">
                                {ownershipManagerName(activeCik, holdings.manager ?? activeCik)} - informe {reportLabel(holdings.report_date)}
                                <span className="ml-2 text-xs font-normal text-gray-500">publicado hasta 45 días después</span>
                            </h2>
                            <Badge className="md:ml-auto" variant="outline">
                                cobertura {holdings.coverage}
                            </Badge>
                        </div>
                        <div aria-label="Posiciones 13F declaradas" className="mt-4 overflow-x-auto" role="region" tabIndex={0}>
                            <table className="w-full min-w-[820px] text-left text-sm">
                                <caption className="sr-only">Posiciones declaradas en el último informe 13F del gestor, tal como constan en EDGAR</caption>
                                <thead className="text-xs uppercase text-gray-500">
                                    <tr>
                                        <th className="border-b border-gray-800 py-2" scope="col">Emisor (tal como se declaró)</th>
                                        <th className="border-b border-gray-800 py-2" scope="col">Clase</th>
                                        <th className="border-b border-gray-800 py-2" scope="col">CUSIP</th>
                                        <th className="border-b border-gray-800 py-2 text-right" scope="col">Valor</th>
                                        <th className="border-b border-gray-800 py-2 text-right" scope="col">Acciones</th>
                                        <th className="border-b border-gray-800 py-2" scope="col">Tipo</th>
                                        <th className="border-b border-gray-800 py-2" scope="col">Filing</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {holdings.holdings.map((row) => (
                                        <tr className="border-b border-gray-900" key={`${row.accession_number}-${row.cusip}-${row.title_of_class}-${row.put_call ?? ''}`}>
                                            <th className="py-3 text-left text-sm font-normal text-gray-200" scope="row">
                                                {row.name_of_issuer}
                                                {row.is_amendment ? (
                                                    <Badge className="ml-2" variant="outline">enmienda</Badge>
                                                ) : null}
                                            </th>
                                            <td className="py-3 text-gray-400">{row.title_of_class || NA}</td>
                                            <td className="py-3 font-mono text-xs text-gray-400">{row.cusip}</td>
                                            <td className="py-3 text-right text-gray-200">{formatValueUsd(row.value_usd_thousands, holdings.report_date)}</td>
                                            <td className="py-3 text-right text-gray-400">{formatShares(row.shares)}</td>
                                            <td className="py-3 text-gray-400">{row.put_call ?? row.share_type}</td>
                                            <td className="py-3">
                                                <a
                                                    className="inline-flex items-center gap-1 text-teal-300 hover:text-teal-200"
                                                    href={row.filing_url}
                                                    rel="noreferrer"
                                                    target="_blank"
                                                >
                                                    <FileText aria-hidden="true" className="h-3.5 w-3.5" />
                                                    XML
                                                    <ExternalLink aria-hidden="true" className="h-3 w-3" />
                                                </a>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                        {holdings.provenance ? (
                            <p className="mt-3 text-xs text-gray-500">
                                Fuente: {holdings.provenance.source} ({holdings.provenance.source_kind}),
                                obtenido {formatUserDateTime(holdings.provenance.fetched_at)}.
                            </p>
                        ) : null}
                    </section>
                ) : (
                    <section className="rounded-xl border border-gray-800 bg-surface-1 p-5 text-sm text-gray-400">
                        <h2 className="font-semibold text-gray-100">Sin datos 13F todavía</h2>
                        <p className="mt-2">Sincroniza para consultar el último informe declarado ante la SEC.</p>
                        <SyncPortfoliosButton label="Sincronizar 13F" queuedText="Sincronización en curso; recarga la página en unos minutos para ver el informe." />
                    </section>
                )
            ) : null}
            {activeCik && changes ? (
                changes.status === 'ok' ? (
                    <section className="rounded-xl border border-gray-800 bg-surface-1 p-5">
                        <div className="flex flex-col gap-2 md:flex-row md:items-center">
                            <h2 className="font-semibold text-gray-100">
                                Cambios trimestre a trimestre ({reportLabel(changes.previous_report)} → {reportLabel(changes.latest_report)})
                                <span className="ml-2 text-xs font-normal text-gray-500">informes publicados hasta 45 días después de cada cierre</span>
                            </h2>
                            <Badge className="md:ml-auto" variant="outline">
                                {formatNumber(changes.changes.filter((c) => c.change !== 'unchanged').length, { maximumFractionDigits: 0 })} movimientos
                            </Badge>
                        </div>
                        <p className="mt-2 text-xs text-gray-500">{changes.compared_accessions?.rule}</p>
                        <div aria-label="Cambios 13F trimestre a trimestre" className="mt-4 overflow-x-auto" role="region" tabIndex={0}>
                            <table className="w-full min-w-[720px] text-left text-sm">
                                <caption className="sr-only">Cambios de cada emisor entre los dos últimos informes 13F, con acciones y valor antes y ahora</caption>
                                <thead className="text-xs uppercase text-gray-500">
                                    <tr>
                                        <th className="border-b border-gray-800 py-2" scope="col">Emisor</th>
                                        <th className="border-b border-gray-800 py-2" scope="col">CUSIP</th>
                                        <th className="border-b border-gray-800 py-2" scope="col">Cambio</th>
                                        <th className="border-b border-gray-800 py-2 text-right" scope="col">Acciones antes</th>
                                        <th className="border-b border-gray-800 py-2 text-right" scope="col">Acciones ahora</th>
                                        <th className="border-b border-gray-800 py-2 text-right" scope="col">Valor antes</th>
                                        <th className="border-b border-gray-800 py-2 text-right" scope="col">Valor ahora</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {changes.changes.filter((row) => row.change !== 'unchanged').map((row) => (
                                        <tr className="border-b border-gray-900" key={`${row.cusip}-${row.title_of_class}-${row.put_call ?? ''}`}>
                                            <th className="py-3 text-left text-sm font-normal text-gray-200" scope="row">{row.name_of_issuer}</th>
                                            <td className="py-3 font-mono text-xs text-gray-400">{row.cusip}</td>
                                            <td className="py-3">
                                                <Badge variant="outline">{CHANGE_LABELS[row.change]}</Badge>
                                            </td>
                                            <td className="py-3 text-right text-gray-400">{formatShares(row.shares_previous)}</td>
                                            <td className="py-3 text-right text-gray-200">{formatShares(row.shares_latest)}</td>
                                            <td className="py-3 text-right text-gray-400">{formatValueUsd(row.value_usd_thousands_previous, changes.previous_report)}</td>
                                            <td className="py-3 text-right text-gray-200">{formatValueUsd(row.value_usd_thousands_latest, changes.latest_report)}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                        {changes.changes.every((c) => c.change === 'unchanged') ? (
                            <p className="mt-3 text-sm text-gray-400">Sin movimientos entre los dos últimos informes.</p>
                        ) : null}
                    </section>
                ) : (
                    <section className="rounded-xl border border-gray-800 bg-surface-1 p-5 text-sm text-gray-400">
                        <h2 className="font-semibold text-gray-100">Cambios trimestrales no disponibles todavía</h2>
                        <p className="mt-2">
                            {changes.status === 'insufficient_history'
                                ? 'Hacen falta dos informes 13F almacenados para comparar; estará disponible tras el próximo trimestre.'
                                : 'Sincroniza este gestor para poder comparar informes.'}
                        </p>
                    </section>
                )
            ) : null}
        </main>
    );
}
