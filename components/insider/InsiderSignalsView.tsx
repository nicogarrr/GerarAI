'use client';

import { formatDate, formatUserDateTime, formatNumber, formatPrice, formatCountEs } from '@/lib/format';
import { t } from '@/lib/i18n/t';
import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ExternalLink, Search, Users } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { TickerSearchInput } from '@/components/search/TickerSearchInput';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { formatRecordValue, type DataRecord } from '@/components/data/RecordViews';
import type { InsiderFilingsResult, InsiderSignalsResult } from '@/lib/actions/insider.actions';
import { loadMoreInsiderFilings } from '@/lib/actions/insider.actions';
import type { InsiderFilingEntry } from '@/lib/actions/insider.actions';
import { insiderCodeLabel, insiderName, insiderRole, signalLabel, signalTooltip } from '@/lib/insider/format';
import { analyzedCountCopy, degradedCopy, persistedSourceCopy, durableReadCopy } from '@/lib/insider-status-copy';

interface InsiderSignalsViewProps {
    initialTicker: string;
    initialResult: InsiderSignalsResult | null;
    /** Filings Form 4/4-A persistidos (GET /api/insider/filings). */
    initialFilings?: InsiderFilingsResult | null;
}

function signalTone(signal: unknown): 'default' | 'outline' {
    return signal === 'cluster_buy' || signal === 'c_suite_buy' || signal === 'big_buy'
        ? 'default'
        : 'outline';
}

function moneyText(value: unknown): string {
    if (typeof value !== 'number' || !Number.isFinite(value)) return formatRecordValue(value);
    return formatPrice(value, 'USD', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

function formBadge(form: unknown): { label: string; amended: boolean } | null {
    if (typeof form !== 'string' || !form) return null;
    if (form.endsWith('/A')) return { label: 'Enmienda ' + form, amended: true };
    return { label: 'Form ' + form, amended: false };
}

function secLink(sourceUrl: unknown): string | null {
    return typeof sourceUrl === 'string' && sourceUrl.startsWith('https://') ? sourceUrl : null;
}

function formatFetchedAt(value: unknown): string {
    if (typeof value !== 'string' || !value) return t('signals.noDate');
    return formatUserDateTime(value);
}

/** Fechas de Form 4: son días del calendario EDGAR (US), no instantes. Se
 *  formatean sin timeZone para que el día salga siempre igual (parseo local +
 *  formato local es invariante de zona). */
function filingDateText(value: unknown): string {
    return typeof value === 'string' && value ? formatDate(value) : formatRecordValue(value);
}

/** Contadores del backend: enteros con separadores es-ES. */
function countText(value: unknown): string {
    return typeof value === 'number' ? formatNumber(value, { maximumFractionDigits: 0 }) : formatRecordValue(value);
}

/** Identidad de la señal: el backend no manda id, así que se compone con los
 *  campos que la definen. `cluster_buy` agrupa a varios insiders en una
 *  ventana; `big_buy`/`c_suite_buy` son compras sueltas de una persona en una
 *  fecha y un formulario. El monitor reordena la lista en cada lectura, así que
 *  `key={index}` hacía que React reutilizara el nodo de otra compra. */
function signalKey(signal: DataRecord): string {
    const type = String(signal.signal ?? 'senal');
    const date = String(signal.date ?? signal.window_start ?? '');
    const form = String(signal.form ?? '');
    const subject = Array.isArray(signal.insiders)
        ? `${String(signal.ticker ?? '')}:${signal.insiders.join('|')}`
        : `${String(signal.insider ?? '')}:${String(signal.source_url ?? '')}`;
    // Identidad por transaccion: dos compras codigo P del mismo insider en la
    // misma fecha (lotes distintos, mismo o distinto fichero) NO comparten
    // clave. accession+line es la identidad estable del backend; shares/price/
    // value (campos de ejecucion) cubren respuestas antiguas sin esos campos.
    const execution = [
        String(signal.accession_number ?? ''),
        String(signal.tx_line ?? ''),
        String(signal.shares ?? ''),
        String(signal.price ?? ''),
        String(signal.value ?? ''),
    ].join(':');
    return `${type}|${subject}|${date}|${form}|${execution}|${formatRecordValue(signal.detail)}`;
}

export default function InsiderSignalsView({ initialTicker, initialResult, initialFilings }: InsiderSignalsViewProps) {
    const router = useRouter();
    const [ticker, setTicker] = useState(initialTicker);

    const handleSearch = (event: React.FormEvent) => {
        event.preventDefault();
        const clean = ticker.trim().toUpperCase();
        if (!clean) return;
        router.push(`/insider?ticker=${encodeURIComponent(clean)}`);
    };

    const signals: DataRecord[] = Array.isArray(initialResult?.signals)
        ? (initialResult.signals as DataRecord[])
        : [];

    // Copy de la lectura durable degradada, resuelto una vez: el `reason` del
    // backend es el nombre de la excepción (`OperationalError`), opaco a pelo.
    const [extraFilings, setExtraFilings] = useState<InsiderFilingEntry[]>([]);
    const [filingsLoading, setFilingsLoading] = useState(false);
    const [filingsError, setFilingsError] = useState(false);
    const baseFilings = initialFilings?.filings ?? [];
    const knownAccessions = new Set(baseFilings.map((filing) => filing.accession_number));
    const filings = [...baseFilings, ...extraFilings.filter((filing) => !knownAccessions.has(filing.accession_number))];
    const filingsTotal = initialFilings?.total ?? initialFilings?.count ?? filings.length;

    async function loadMoreFilings() {
        if (filingsLoading || !initialTicker) return;
        setFilingsLoading(true);
        setFilingsError(false);
        try {
            const next = await loadMoreInsiderFilings(initialTicker, filings.length);
            if (next.status !== 'ok') throw new Error(next.reason ?? next.status);
            setExtraFilings((current) => [...current, ...next.filings]);
        } catch {
            setFilingsError(true);
        } finally {
            setFilingsLoading(false);
        }
    }

    const durable = initialFilings && initialFilings.status !== 'ok'
        ? durableReadCopy(initialFilings)
        : null;

    return (
        <div className="grid w-full min-w-0 grid-cols-1 gap-6">
            <form onSubmit={handleSearch} className="flex w-full max-w-md items-start gap-2">
                <TickerSearchInput
                    value={ticker}
                    onValueChange={setTicker}
                    onSelect={(stock) => router.push(`/insider?ticker=${encodeURIComponent(stock.symbol.toUpperCase())}`)}
                    placeholder="Buscar por ticker o empresa"
                    ariaLabel={t('insider.searchPlaceholder')}
                    className="h-11 w-full bg-gray-900"
                />
                <Button type="submit" className="h-11 shrink-0 gap-2">
                    <Search aria-hidden="true" className="h-4 w-4" />
                    Buscar
                </Button>
            </form>

            {/* Solo fallos que afectan a la lectura, no telemetría del monitor. */}
            {initialTicker ? (
                <div className="flex flex-wrap items-center gap-2">
                    {(!initialResult || !initialFilings) ? (
                        <span className="text-xs text-amber-300">
                            Lectura parcial: una de las fuentes no respondió. Reintenta la búsqueda.
                        </span>
                    ) : null}
                    {durable ? (
                        <span className="max-w-xl text-xs leading-5 text-amber-300">
                            {durable.header}
                            {durable.detail ? (
                                <span className="block text-amber-300/80">
                                    Detalle técnico: {durable.detail}
                                </span>
                            ) : null}
                        </span>
                    ) : null}
                </div>
            ) : null}

            {!initialTicker ? null : !initialResult ? (
                <p className="rounded-lg border border-red-900/50 bg-red-950/20 p-6 text-sm text-red-200">
                    No se pudieron cargar las señales de {initialTicker}. Reintenta más tarde.
                </p>
            ) : initialResult.status === 'unavailable' ? (
                <div className="rounded-lg border border-amber-900/60 bg-amber-950/20 p-6 text-sm text-amber-200">
                    {/* unavailable solo se devuelve cuando el ticker no resuelve CIK en EDGAR:
                        eso prueba «no es emisor SEC US», nada mas. La reason estable
                        («not a US SEC filer») ya la dice la cabecera; otra reason seria detalle. */}
                    <p>
                        {initialTicker}: no es un emisor SEC estadounidense (sin CIK en EDGAR), así
                        que no tiene señales insider Form 4.
                    </p>
                    {typeof initialResult.reason === 'string' &&
                    initialResult.reason &&
                    initialResult.reason !== 'not a US SEC filer' ? (
                        <p className="mt-2 text-xs text-amber-300/80">
                            Detalle técnico: {formatRecordValue(initialResult.reason)}
                        </p>
                    ) : null}
                </div>
            ) : initialResult.status === 'degraded' ? (
                // F234: «AAPL: degraded» a pelo no decía nada. El backend ya
                // devuelve cuántos Form 4 se escanearon y cuántos fallaron:
                // un estado técnico se explica con sus números, nunca con la
                // palabra cruda. Y se deja claro que no es un «sin actividad».
                <div className="rounded-lg border border-amber-900/60 bg-amber-950/20 p-6 text-sm text-amber-200">
                    <p>
                        {degradedCopy(initialTicker, initialResult, countText).header} Es un fallo
                        de lectura, no una ausencia de actividad insider.
                        {initialFilings && initialFilings.status === 'ok' && initialFilings.filings.length > 0
                            /* Con filings guardados debajo, «reintenta más tarde» a pelo
                               contradecía la lista visible: el aviso declara que la lectura
                               en vivo falló y que debajo está la copia guardada. */
                            ? ` Debajo se muestran los ${countText(initialFilings.total ?? initialFilings.filings.length)} filings guardados; la actualización en vivo desde EDGAR se reintentará en el próximo ciclo del monitor.`
                            : ' Reintenta más tarde.'}
                    </p>
                    {degradedCopy(initialTicker, initialResult, countText).detail ? (
                        <p className="mt-2 text-xs text-amber-300/80">
                            Detalle técnico: {degradedCopy(initialTicker, initialResult, countText).detail}
                        </p>
                    ) : null}
                </div>
            ) : (
                // ok y partial: las señales parseadas son reales; partial las
                // muestra con su aviso de cobertura incompleta.
                <>
                    {initialResult.status === 'partial' ? (
                        <p className="rounded-lg border border-amber-900/60 bg-amber-950/20 p-6 text-sm text-amber-200">
                            {(initialResult.filings_failed ?? 0) > 0 ? (
                                <>
                                    {initialTicker}: lectura incompleta — {countText(initialResult.filings_parsed)} de{' '}
                                    {countText(initialResult.filings_scanned)} Form 4 leídos (
                                    {countText(initialResult.filings_failed)} con error). Las señales de abajo
                                    cubren solo los filings legibles.{' '}
                                </>
                            ) : null}
                            {Array.isArray(initialResult.warnings) && initialResult.warnings.length
                                ? `${initialTicker}: ${initialResult.warnings.join(' ')}`
                                : null}
                        </p>
                    ) : null}
                    {persistedSourceCopy(initialTicker, initialResult, countText) ? (
                        <p className="rounded-lg border border-amber-900/60 bg-amber-950/20 p-6 text-sm text-amber-200">
                            {persistedSourceCopy(initialTicker, initialResult, countText)}
                        </p>
                    ) : null}
                    {signals.length === 0 ? (
                        <p className="rounded-lg border border-dashed border-gray-800 p-6 text-sm text-gray-500">
                            {initialTicker}: {t('insider.noSignals')} (
                            {analyzedCountCopy(initialResult.status, initialResult, countText)}).
                        </p>
                    ) : (
                <Card className="rounded-lg border border-gray-700 bg-gray-800/50">
                    <CardHeader className="flex flex-col gap-3 space-y-0 border-b border-gray-700/50 pb-4 sm:flex-row sm:items-center sm:justify-between">
                        <div className="flex items-center gap-3">
                            <Users aria-hidden="true" className="h-5 w-5 text-teal-400" />
                            <div>
                                <CardTitle className="text-lg font-semibold text-gray-100">
                                    Señales ·{' '}
                                    <Link
                                        href={`/research/${encodeURIComponent(initialTicker)}`}
                                        className="font-mono text-teal-300 hover:text-teal-200 hover:underline"
                                    >
                                        {initialTicker}
                                    </Link>
                                </CardTitle>
                                <CardDescription className="mt-0.5 text-sm text-gray-500">
                                    {formatCountEs(signals.length, 'señal', 'señales')} ·{' '}
                                    {countText(initialResult.buy_count)} compras ·{' '}
                                    {countText(initialResult.filings_scanned)} filings · datos al{' '}
                                    {t('signals.asOf', { date: formatFetchedAt((initialResult.provenance as Record<string, unknown> | undefined)?.fetched_at ?? initialResult.fetched_at) })}
                                </CardDescription>
                            </div>
                        </div>
                        <div className="flex flex-wrap gap-2">
                            <Badge>cluster</Badge>
                            <Badge variant="outline">C-suite</Badge>
                        </div>
                    </CardHeader>
                    <CardContent className="min-w-0 pt-4">
                        <div className="hidden md:block">
                        <Table regionLabel="Señales insider del ticker">
                            <TableCaption className="sr-only">Compras insider registradas: tipo de señal, persona, fecha, importe y detalle con enlace al filing de la SEC.</TableCaption>
                            <TableHeader>
                                <TableRow className="border-gray-700 hover:bg-transparent">
                                    <TableHead className="text-xs font-semibold uppercase text-gray-500">{t('insider.signal')}</TableHead>
                                    <TableHead className="text-xs font-semibold uppercase text-gray-500">{t('insider.insider')}</TableHead>
                                    <TableHead className="text-xs font-semibold uppercase text-gray-500">{t('insider.date')}</TableHead>
                                    <TableHead className="text-right text-xs font-semibold uppercase text-gray-500">{t('insider.value')}</TableHead>
                                    <TableHead className="text-xs font-semibold uppercase text-gray-500">{t('insider.detail')}</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {signals.map((signal) => (
                                    <TableRow key={signalKey(signal)} className="border-gray-700/50">
                                        <TableCell>
                                            <Badge
                                                variant={signalTone(signal.signal)}
                                                title={signalTooltip(typeof signal.signal === 'string' ? signal.signal : null)}
                                            >
                                                {signalLabel(typeof signal.signal === 'string' ? signal.signal : null)}
                                            </Badge>
                                        </TableCell>
                                        <TableCell className="text-sm text-gray-200">
                                            {formatRecordValue(signal.insider)}
                                            {signal.officer_title ?? signal.role ? (
                                                <span className="block text-xs text-gray-500">
                                                    {/* Mismo mapa de cargos que el feed: aquí salía el título SEC en crudo (Tester 6). */}
                                                    {insiderRole(
                                                        typeof signal.role === 'string' ? signal.role : null,
                                                        typeof signal.officer_title === 'string' ? signal.officer_title : null,
                                                    )}
                                                </span>
                                            ) : null}
                                        </TableCell>
                                        <TableCell className="text-sm text-gray-300">
                                            {filingDateText(signal.date ?? signal.window_start)}
                                        </TableCell>
                                        <TableCell className="text-right text-sm font-semibold text-gray-100">
                                            {moneyText(signal.value ?? signal.total_value)}
                                        </TableCell>
                                        <TableCell className="max-w-md text-sm text-gray-400">
                                            <span className="line-clamp-3">{formatRecordValue(signal.detail)}</span>
                                            <span className="mt-1 flex flex-wrap items-center gap-2">
                                                {formBadge(signal.form) ? (
                                                    <Badge variant="outline">{formBadge(signal.form)!.label}</Badge>
                                                ) : null}
                                                {signal.multi_reporter === true ? (
                                                    <span className="text-xs text-gray-500">filing conjunto</span>
                                                ) : null}
                                                {secLink(signal.source_url) ? (
                                                    <a
                                                        href={secLink(signal.source_url)!}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        className="inline-flex items-center gap-1 text-xs text-teal-300 hover:text-teal-200 hover:underline"
                                                    >
                                                        Ver filing SEC <ExternalLink aria-hidden="true" className="h-3 w-3" />
                                                    </a>
                                                ) : null}
                                            </span>
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                        </div>
                        <div className="grid grid-cols-1 gap-3 md:hidden">
                            {signals.map((signal) => (
                                <article className="min-w-0 rounded-lg border border-gray-700/50 bg-gray-900/50 p-4 break-words" key={signalKey(signal)}>
                                    <div className="flex flex-wrap items-center gap-2">
                                        <Badge variant={signalTone(signal.signal)} title={signalTooltip(typeof signal.signal === 'string' ? signal.signal : null)}>{signalLabel(typeof signal.signal === 'string' ? signal.signal : null)}</Badge>
                                        <span className="ml-auto text-sm font-semibold text-gray-100">{moneyText(signal.value ?? signal.total_value)}</span>
                                    </div>
                                    <div className="mt-3 text-sm font-medium text-gray-200">{formatRecordValue(signal.insider)}</div>
                                    {signal.officer_title ?? signal.role ? (
                                        <div className="text-xs text-gray-500">
                                            {insiderRole(
                                                typeof signal.role === 'string' ? signal.role : null,
                                                typeof signal.officer_title === 'string' ? signal.officer_title : null,
                                            )}
                                        </div>
                                    ) : null}
                                    <div className="mt-1 text-xs text-gray-500">{filingDateText(signal.date ?? signal.window_start)}</div>
                                    <div className="mt-2 text-sm leading-6 text-gray-400"><span className="line-clamp-3">{formatRecordValue(signal.detail)}</span></div>
                                    <div className="mt-2 flex flex-wrap items-center gap-2">
                                        {formBadge(signal.form) ? <Badge variant="outline">{formBadge(signal.form)!.label}</Badge> : null}
                                        {signal.multi_reporter === true ? <span className="text-xs text-gray-500">filing conjunto</span> : null}
                                        {secLink(signal.source_url) ? (
                                            <a
                                                href={secLink(signal.source_url)!}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="inline-flex items-center gap-1 text-xs text-teal-300 hover:text-teal-200 hover:underline"
                                            >
                                                Ver filing SEC <ExternalLink aria-hidden="true" className="h-3 w-3" />
                                            </a>
                                        ) : null}
                                    </div>
                                </article>
                            ))}
                        </div>
                    </CardContent>
                </Card>
                    )}
                </>
            )}
            {initialTicker && initialFilings && initialFilings.status === 'ok' && initialFilings.filings.length > 0 ? (
                <Card className="rounded-lg border border-gray-700 bg-gray-800/50">
                    <CardHeader className="border-b border-gray-700/50 pb-4">
                        <CardTitle className="text-lg font-semibold text-gray-100">
                            Filings persistidos · {initialFilings.total ?? initialFilings.count}
                        </CardTitle>
                    </CardHeader>
                    <CardContent className="pt-4">
                        <ul className="space-y-2">
                            {filings.map((filing) => (
                                <li key={filing.accession_number} className="rounded-lg border border-gray-800 p-3 text-sm">
                                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                                        <Badge variant="outline">{filing.form}</Badge>
                                        {filing.is_amendment ? <Badge>Enmienda</Badge> : null}
                                        <span className="font-mono text-gray-300">
                                            {filingDateText(filing.filing_date)}
                                        </span>
                                        {secLink(filing.source_url) ? (
                                            <a
                                                href={secLink(filing.source_url)!}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="inline-flex items-center gap-1 text-xs text-teal-300 hover:text-teal-200 hover:underline"
                                            >
                                                Ver filing SEC <ExternalLink aria-hidden="true" className="h-3 w-3" />
                                            </a>
                                        ) : null}
                                    </div>
                                    {filing.transactions.length > 0 ? (
                                        <ul className="mt-2 space-y-1">
                                            {filing.transactions.map((tx, index) => (
                                                <li className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs" key={index}>
                                                    <span className="font-semibold text-gray-100">{insiderName(tx.insider)}</span>
                                                    <span className="text-gray-400">{insiderRole(tx.role, tx.officer_title)}</span>
                                                    <span className={tx.code === 'P' ? 'text-teal-300' : tx.code === 'S' ? 'text-red-400' : 'text-gray-400'}>
                                                        {insiderCodeLabel(tx.code)}
                                                        {tx.is_derivative ? ' · derivado' : ''}
                                                        {tx.security_title ? ` · ${tx.security_title}` : ''}
                                                        {tx.rule_10b5_1 ? ' · plan 10b5-1' : ''}
                                                    </span>
                                                    <span className="tabular-nums text-gray-300">{formatNumber(tx.shares ?? null, { maximumFractionDigits: 0 })} acc.</span>
                                                    {tx.price !== null && tx.price !== undefined ? (
                                                        <span className="tabular-nums text-gray-300">{moneyText(tx.price)}</span>
                                                    ) : null}
                                                    {tx.value !== null && tx.value !== undefined && !(tx.value === 0 && tx.code !== 'P' && tx.code !== 'S') ? (
                                                        <span className="tabular-nums text-gray-100">{moneyText(tx.value)}</span>
                                                    ) : null}
                                                </li>
                                            ))}
                                        </ul>
                                    ) : (
                                        <p className="mt-2 text-xs text-gray-500">Sin operaciones extraídas.</p>
                                    )}
                                </li>
                            ))}
                        </ul>
                        <div className="mt-4 flex flex-col items-center gap-2 text-xs text-gray-500">
                            <span>
                                Mostrando {filings.length} de {filingsTotal}
                            </span>
                            {filingsError ? (
                                <span className="text-red-400" role="alert">
                                    No se pudieron cargar más filings.
                                </span>
                            ) : null}
                            {filings.length < filingsTotal ? (
                                <Button
                                    disabled={filingsLoading}
                                    onClick={() => void loadMoreFilings()}
                                    size="sm"
                                    type="button"
                                    variant="outline"
                                >
                                    {filingsLoading ? 'Cargando…' : filingsError ? 'Reintentar' : 'Cargar más'}
                                </Button>
                            ) : null}
                        </div>
                    </CardContent>
                </Card>
            ) : null}
        </div>
    );
}
