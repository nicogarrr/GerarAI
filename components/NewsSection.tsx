import { ExternalNewsHeadline } from '@/components/research/ExternalNewsHeadline';
import { getNews } from '@/lib/actions/finnhub.actions';
import { newsSummaryToShow } from '@/lib/news-summary';
import { getT } from '@/lib/i18n/server';
import { newsBadge } from '@/lib/newsBadge';
import { stripLeadingTicker, stripSourceSuffix } from '@/lib/news-display';
import { formatMarketDateTime } from '@/lib/format';
import Image from 'next/image';
import Link from 'next/link';
import { RefreshCcw } from 'lucide-react';

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
                    {t('common.actions.retry')}
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
                    <div className="space-y-3 sm:space-y-4">
                        {news.map((article, index) => {
                            // La insignia del ticker se calcula una vez por tarjeta y
                            // enlaza a la ficha de la compañía (patrón de enlace
                            // estirado: la <a> externa cubre la tarjeta y la insignia
                            // queda por encima con z-10, sin enlaces anidados).
                            const badge = newsBadge(article, symbols);
                            return (
                            <article
                                key={`${article.id}-${index}`}
                                className="relative min-w-0 p-4 bg-surface-2 hover:bg-surface-1 rounded-lg border border-gray-800 transition-all duration-200 group"
                            >
                            <div className="mb-2 flex justify-end">
                                {badge.kind === 'general' ? <span className="text-xs text-gray-400">{t('home.news.generalMarket')}</span> : <Link href={`/research/${encodeURIComponent(badge.ticker)}`} className="text-xs text-teal-300">{badge.kind === 'mentioned' ? t('home.news.mentioned', { ticker: badge.ticker }) : badge.ticker}</Link>}
                            </div>
                            <div>
                                <div className="flex flex-col min-[420px]:flex-row gap-3 sm:gap-4">
                                    {article.image && (
                                        <div className="h-28 w-full min-w-0 shrink-0 relative rounded-lg overflow-hidden min-[420px]:h-24 min-[420px]:w-32">
                                            <Image
                                                src={article.image}
                                                /* El titular ya está en el <h3> de al lado: con alt
                                                   textual el lector de pantalla lo anuncia dos veces. */
                                                alt=""
                                                fill
                                                className={
                                                    /* Logos de fuente (p.ej. Reuters): contain para
                                                       no cortar la palabra; fotos: cover como antes. */
                                                    article.image.includes('/logo/')
                                                        ? 'object-contain bg-black/40 p-2'
                                                        : 'object-cover'
                                                }
                                                sizes="(min-width: 420px) 128px, 100vw"
                                            />
                                        </div>
                                    )}
                                    <div className="flex-1 min-w-0">
                                        <ExternalNewsHeadline
                                            headline={stripLeadingTicker(stripSourceSuffix(article.headline, article.source), badge.kind === 'general' ? null : badge.ticker)}
                                            url={article.url}
                                            className="text-white text-sm sm:text-base font-semibold mb-2 break-words"
                                        />
                                        {newsSummaryToShow(article.headline, article.summary) && (
                                            <p className="text-gray-400 text-sm mb-2 line-clamp-2 break-words">
                                                {newsSummaryToShow(article.headline, article.summary)}
                                            </p>
                                        )}
                                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
                                            {article.source && (
                                                <span className="font-medium text-[#0FEDBE]">
                                                    {article.source}
                                                </span>
                                            )}
                                            {typeof article.datetime === 'number' && Number.isFinite(article.datetime) && article.datetime > 0 ? (
                                                <span>
                                                    {formatMarketDateTime(new Date(article.datetime * 1000), {
                                                        day: 'numeric',
                                                        month: 'short',
                                                        year: 'numeric',
                                                        hour: '2-digit',
                                                        minute: '2-digit',
                                                    })}
                                                </span>
                                            ) : <span>{t('home.news.noDate')}</span>}
                                        </div>
                                    </div>
                                </div>
                            </div>
                            </article>
                        );})}
                    </div>
                )}
            </section>
    );
}

