'use client';

import { useCallback, useEffect, useState } from 'react';
import { RefreshCcw } from 'lucide-react';

import { getLiveMarkets } from '@/lib/actions/live-quotes.actions';
import {
    formatQuoteAge,
    formatQuoteChange,
    formatQuoteChangePercent,
    localizeInstrumentType,
    quoteAgeSeconds,
    resolveGroupRows,
    type LiveMarketsResult,
    type LiveQuote,
    type LiveQuoteKind,
    type LiveQuoteSpec,
} from '@/lib/market/live-quotes';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { useFormat, useLocale, useT } from '@/lib/i18n/client';
import type { Locale } from '@/lib/i18n/locale';
import type { TranslateFn } from '@/lib/i18n/translate';

const POLL_MS = 60_000;

const TABS = [
    { key: 'indice', label: 'markets.live.tabs.indice', note: 'markets.live.notes.indice' },
    { key: 'futuro', label: 'markets.live.tabs.futuro', note: 'markets.live.notes.futuro' },
    { key: 'accion', label: 'markets.live.tabs.accion', note: 'markets.live.notes.accion' },
    { key: 'materia', label: 'markets.live.tabs.materia', note: 'markets.live.notes.materia' },
    { key: 'divisa', label: 'markets.live.tabs.divisa', note: 'markets.live.notes.divisa' },
] as const satisfies readonly { key: LiveQuoteKind; label: Parameters<TranslateFn>[0]; note: Parameters<TranslateFn>[0] }[];

const priceFormatter = (unit: LiveQuote['unit'], decimals: number, locale: Locale) =>
    new Intl.NumberFormat(locale === 'en' ? 'en-US' : 'es-ES', {
        style: unit === 'index' || unit === 'cruz' ? 'decimal' : 'currency',
        currency: unit === 'index' || unit === 'cruz' ? undefined : unit,
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    });

const timeFormatter = (locale: Locale) => new Intl.DateTimeFormat(locale === 'en' ? 'en-GB' : 'es-ES', {
    timeZone: 'Europe/Madrid',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
});

function formatPrice(quote: LiveQuote, locale: Locale): string {
    return priceFormatter(quote.unit, quote.decimals, locale).format(quote.price);
}

function sessionLabel(session: LiveQuote['session'], t: TranslateFn): string | null {
    if (session === 'pre') return t('markets.live.premarket');
    if (session === 'post') return t('markets.live.postmarket');
    return null;
}

function identityLine(quote: LiveQuote, locale: Locale): string {
    const parts = [quote.symbol];
    if (quote.exchangeName) parts.push(quote.exchangeName);
    const kindLabel = localizeInstrumentType(quote.instrumentType, locale);
    if (kindLabel) parts.push(kindLabel);
    return parts.join(' · ');
}

function QuoteRow({ spec, quote, fetchedAt }: { spec: LiveQuoteSpec; quote: LiveQuote | null; fetchedAt: number }) {
    const t = useT();
    const locale = useLocale();
    const { na } = useFormat();
    if (!quote) {
        // El proveedor fallo para ESTE instrumento: la fila conserva su
        // identidad (nombre + simbolo) y solo el dato queda N/D.
        return (
            <tr className="border-b border-gray-800/60">
                <td className="py-2.5 pr-2">
                    <div className="text-gray-100">{spec.name}</div>
                    <div className="text-xs text-gray-500">{spec.symbol}</div>
                </td>
                <td className="py-2.5 px-2 text-right text-gray-500 whitespace-nowrap" colSpan={2}>{na}</td>
            </tr>
        );
    }
    const changeClass = quote.changePercent === null ? 'text-gray-500' : quote.changePercent >= 0 ? 'text-good' : 'text-bad';
    const age = quoteAgeSeconds(fetchedAt, quote.timestamp);
    const session = sessionLabel(quote.session, t);
    return (
        <tr className="border-b border-gray-800/60">
            <td className="py-2.5 pr-2">
                <div className="text-gray-100">{quote.name}</div>
                <div className="text-xs text-gray-500">{identityLine(quote, locale)}</div>
                <div className="text-xs text-gray-500">
                    {quote.timestamp ? timeFormatter(locale).format(new Date(quote.timestamp * 1000)) : t('markets.live.noTime')}
                    {/* La frase de edad es una unidad inseparable: si la linea
                        no cabe (390 + autosizing), salta entera a la 2ª linea
                        en vez de dejar "min" huerfano. No se recorta dato. */}
                    {age !== null ? (
                        <>
                            {' · '}
                            <span className="whitespace-nowrap">{formatQuoteAge(age, locale)}</span>
                        </>
                    ) : ''}
                    {session ? ` · ${session}` : ''}
                </div>
            </td>
            <td className="py-2.5 px-2 text-right font-medium text-gray-100 whitespace-nowrap">{formatPrice(quote, locale)}</td>
            <td className={`py-2.5 pl-2 text-right whitespace-nowrap ${changeClass}`}>
                {quote.change === null || quote.changePercent === null ? (
                    na
                ) : (
                    <>
                        <div>{formatQuoteChange(quote.change, quote.decimals, locale)}</div>
                        <div className="text-xs">({formatQuoteChangePercent(quote.changePercent, locale)}%)</div>
                    </>
                )}
            </td>
        </tr>
    );
}

export function LiveMarketsPanel({ initial }: { initial: LiveMarketsResult | null }) {
    const t = useT();
    const locale = useLocale();
    const [data, setData] = useState<LiveMarketsResult | null>(initial);
    const [refreshing, setRefreshing] = useState(false);
    const [failed, setFailed] = useState(false);

    const refresh = useCallback(async () => {
        setRefreshing(true);
        try {
            const next = await getLiveMarkets();
            setData(next);
            setFailed(false);
        } catch {
            // Conservamos lo ultimo bueno; la antigüedad por fila sigue siendo honesta.
            setFailed(true);
        } finally {
            setRefreshing(false);
        }
    }, []);

    useEffect(() => {
        const timer = setInterval(refresh, POLL_MS);
        return () => clearInterval(timer);
    }, [refresh]);

    return (
        <div className="mt-4">
            <div className="flex items-center justify-between gap-2 text-xs text-gray-500">
                <span>
                    {data
                        ? t('markets.live.updatedAt', { time: timeFormatter(locale).format(new Date(data.fetchedAt)) })
                        : t('markets.live.noData')}
                    {failed ? t('markets.live.lastFailed') : ''}
                </span>
                <Button className="min-w-11" variant="ghost" size="sm" onClick={refresh} disabled={refreshing} aria-label={t('markets.live.refresh')}>
                    <RefreshCcw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
                </Button>
            </div>
            <Tabs defaultValue="indice" className="mt-3">
                {/* h-auto: con flex-wrap la lista crece a 2 filas en móvil; con la
                    altura fija base (h-9) la 2ª fila se montaba sobre el texto
                    siguiente y esas tabs no respondían al toque (21-oct-2026). */}
                <TabsList className="h-auto flex-wrap gap-y-1">
                    {TABS.map((tab) => (
                        <TabsTrigger className="min-h-11" key={tab.key} value={tab.key}>{t(tab.label)}</TabsTrigger>
                    ))}
                </TabsList>
                {TABS.map((tab) => {
                    const group = data?.groups.find((g) => g.key === tab.key) ?? null;
                    return (
                        <TabsContent key={tab.key} value={tab.key}>
                            <p className="mb-2 text-xs text-gray-500">{t(tab.note)}</p>
                            {group ? (
                                <table className="w-full text-sm">
                                    <tbody>
                                        {resolveGroupRows(tab.key, group.quotes).map(({ spec, quote }) => (
                                            <QuoteRow key={spec.symbol} spec={spec} quote={quote} fetchedAt={data?.fetchedAt ?? 0} />
                                        ))}
                                    </tbody>
                                </table>
                            ) : (
                                <p className="py-6 text-center text-sm text-gray-500">
                                    {t('markets.live.groupEmpty')}
                                </p>
                            )}
                        </TabsContent>
                    );
                })}
            </Tabs>
            <p className="mt-4 text-xs leading-5 text-gray-500">
                {t('markets.live.footer')}
            </p>
        </div>
    );
}
