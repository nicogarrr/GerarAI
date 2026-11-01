import { ExternalNewsHeadline } from '@/components/research/ExternalNewsHeadline';
import { CompanyLogo } from '@/components/calendar/CompanyLogo';
import { getNews } from '@/lib/actions/finnhub.actions';
import { getLocale, getT } from '@/lib/i18n/server';
import { newsBadge } from '@/lib/newsBadge';
import { dedupeArticles, stripLeadingTicker, stripSourceSuffix } from '@/lib/news-display';
import { formatAgeShort, formatMarketDate } from '@/lib/format';
import Link from 'next/link';
import { Newspaper, RefreshCcw } from 'lucide-react';

interface NewsSectionProps {
    symbols?: string[];
}

/**
 * ÚNICA sección de noticias del dashboard (la tarjeta por símbolo de
 * PersonalizedOverview se eliminó: duplicaba esta y añadía 5 llamadas a Finnhub
 * por carga). Es un server component, así que llega por streaming al final del
 * scroll sin coste de JS de cliente.
 */
export default async function NewsSection({ symbols }: NewsSectionProps) {
    const t = await getT();
    const locale = await getLocale();
    let news;
    try {
        news = await getNews(symbols);
    } catch {
        return (
            <section aria-label={t('home.news.title')} className="w-full min-w-0 rounded-lg border border-amber-900/60 bg-amber-950/20 p-6 text-center">
                <p className="text-sm leading-6 text-amber-200">
                    {t('home.news.error')}
                </p>
                {/* «Reintentar» recarga Inicio (vuelve a pedir las noticias). Antes
                    llevaba a /research/news: el botón decía reintentar y
                    cambiaba de página. Enlace normal, no <Link>: la navegación
                    cliente a la misma URL puede servirse de la caché del router. */}
                <a
                    className="mt-3 inline-flex min-h-[44px] items-center gap-2 rounded-lg border border-amber-400/30 px-4 text-sm text-amber-200 transition-colors hover:text-amber-100"
                    href="/inicio"
                >
                    <RefreshCcw aria-hidden="true" className="h-4 w-4" />
                    Reintentar
                </a>
            </section>
        );
    }

    return (
            <section aria-label={t('home.news.title')} className="w-full min-w-0 h-full bg-surface-1 rounded-lg border border-gray-800 p-4 sm:p-6 overflow-y-auto">
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3 sm:mb-6">
                    <h2 className="text-xl sm:text-2xl font-bold text-white break-words">{t('home.news.title')}</h2>
                    <Link
                        className="inline-flex min-h-[44px] items-center rounded-lg border border-teal-400/20 px-3 text-xs text-teal-400 transition-colors hover:text-teal-300"
                        href="/research/news"
                    >
                        {t('home.news.analysisLink')}
                    </Link>
                </div>

                {news.length === 0 ? (
                    <div className="flex items-center justify-center px-4 py-12 text-center text-sm text-gray-500">
                        <p>{t('home.news.empty')}</p>
                    </div>
                ) : (
                    // Filas estilo feed (referencia Quartr, pedido de Nico 1-nov-2026):
                    // logo de la empresa, nombre, titular y antigüedad compacta. Sin
                    // imagen, sin fuente pintada y sin duplicados (dedupeArticles).
                    <ul className="divide-y divide-gray-800">
                        {dedupeArticles(news).map((article, index) => {
                            // La insignia del ticker se calcula una vez por fila (F149:
                            // mencionada vs. cartera) y el bloque logo+nombre ES la
                            // insignia: enlaza a la ficha con área táctil de 44 px.
                            const badge = newsBadge(article, symbols);
                            const ticker = badge.kind === 'general' ? null : badge.ticker;
                            const age =
                                typeof article.datetime === 'number' && Number.isFinite(article.datetime) && article.datetime > 0
                                    ? (formatAgeShort(article.datetime, Date.now(), locale) ??
                                      formatMarketDate(new Date(article.datetime * 1000), { day: 'numeric', month: 'short' }))
                                    : t('home.news.noDate');
                            return (
                                <li key={`${article.id}-${index}`} className="flex items-start gap-3 py-3">
                                    {ticker ? (
                                        <Link
                                            href={`/research/${encodeURIComponent(ticker)}`}
                                            aria-label={ticker}
                                            className="mt-0.5 shrink-0"
                                        >
                                            <CompanyLogo ticker={ticker} name={ticker} className="size-12 rounded-xl" />
                                        </Link>
                                    ) : (
                                        <span aria-hidden="true" className="mt-0.5 grid size-12 shrink-0 place-items-center rounded-xl bg-gray-800 text-gray-400">
                                            <Newspaper className="size-5" />
                                        </span>
                                    )}
                                    <div className="min-w-0 flex-1">
                                        <p className="flex items-baseline justify-between gap-3">
                                            {ticker ? (
                                                <Link
                                                    href={`/research/${encodeURIComponent(ticker)}`}
                                                    className="relative truncate text-sm font-semibold text-gray-100 before:absolute before:-inset-3.5 before:content-[''] hover:text-teal-200"
                                                >
                                                    {badge.kind === 'mentioned' ? `Mencionada · ${ticker}` : ticker}
                                                </Link>
                                            ) : (
                                                <span className="truncate text-sm font-semibold text-gray-100">{t('home.news.generalMarket')}</span>
                                            )}
                                            <span className="shrink-0 text-xs text-gray-500">{age}</span>
                                        </p>
                                        <ExternalNewsHeadline
                                            headline={stripLeadingTicker(stripSourceSuffix(article.headline, article.source), ticker)}
                                            url={article.url}
                                            className="mt-1 text-sm leading-6 text-gray-400 line-clamp-3 break-words"
                                        />
                                    </div>
                                </li>
                            );
                        })}
                    </ul>
                )}
            </section>
    );
}

