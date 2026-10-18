import { getNews } from '@/lib/actions/finnhub.actions';
import { newsSummaryToShow } from '@/lib/news-summary';
import { newsBadge } from '@/lib/newsBadge';
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
    let news;
    try {
        news = await getNews(symbols);
    } catch {
        return (
            <section aria-label="Noticias destacadas" className="w-full min-w-0 rounded-lg border border-amber-900/60 bg-amber-950/20 p-6 text-center">
                <p className="text-sm leading-6 text-amber-200">
                    No se pudieron cargar las noticias. El resto del dashboard sigue funcionando.
                </p>
                <Link
                    className="mt-3 inline-flex min-h-[44px] items-center gap-2 rounded-lg border border-amber-400/30 px-4 text-sm text-amber-200 transition-colors hover:text-amber-100"
                    href="/research/news"
                >
                    <RefreshCcw aria-hidden="true" className="h-4 w-4" />
                    Reintentar
                </Link>
            </section>
        );
    }

    return (
            <section aria-label="Noticias destacadas" className="w-full min-w-0 h-full bg-surface-1 rounded-lg border border-gray-800 p-4 sm:p-6 overflow-y-auto">
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3 sm:mb-6">
                    <h2 className="text-xl sm:text-2xl font-bold text-white break-words">Noticias destacadas</h2>
                    <Link
                        className="inline-flex min-h-[44px] items-center rounded-lg border border-teal-400/20 px-3 text-xs text-teal-400 transition-colors hover:text-teal-300"
                        href="/research/news"
                    >
                        Ver el análisis de noticias
                    </Link>
                </div>

                {news.length > 0 && (
                    <p className="mb-3 text-xs leading-5 text-gray-500">
                        {symbols?.length
                            ? 'Titulares vinculados a tus símbolos cuando los hay (insignia con el ticker); el resto menciona otras compañías o es mercado general, sin vínculo con tu cartera.'
                            : 'Titulares de mercado general. La insignia indica la compañía mencionada en el titular, no una posición tuya.'}
                    </p>
                )}
                {news.length === 0 ? (
                    <div className="flex items-center justify-center px-4 py-12 text-center text-sm text-gray-500">
                        <p>No hay noticias disponibles en este momento.</p>
                    </div>
                ) : (
                    <div className="space-y-3 sm:space-y-4">
                        {news.map((article, index) => (
                            <a
                                key={`${article.id}-${index}`}
                                href={article.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="block min-w-0 p-4 bg-surface-2 hover:bg-surface-1 rounded-lg border border-gray-800 transition-all duration-200 group"
                            >
                                <div className="flex flex-col min-[420px]:flex-row gap-3 sm:gap-4">
                                    {article.image && (
                                        <div className="h-40 w-full min-w-0 shrink-0 relative rounded-lg overflow-hidden min-[420px]:h-24 min-[420px]:w-32">
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
                                        <h3 className="text-white text-sm sm:text-base font-semibold mb-2 line-clamp-2 group-hover:text-[#0FEDBE] transition-colors break-words">
                                            {article.headline}
                                        </h3>
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
                                            {article.datetime && (
                                                <span>
                                                    {formatMarketDateTime(new Date(article.datetime * 1000), {
                                                        day: 'numeric',
                                                        month: 'short',
                                                        year: 'numeric',
                                                        hour: '2-digit',
                                                        minute: '2-digit',
                                                    })}
                                                </span>
                                            )}
                                            {(() => {
                                                // related del proveedor = compañía mencionada, NO tenencia:
                                                // «holding» solo si el ticker está entre los símbolos del usuario.
                                                const badge = newsBadge(article, symbols);
                                                if (badge.kind === 'holding') {
                                                    return (
                                                        <span className="px-2 py-0.5 bg-[#0FEDBE]/10 text-[#0FEDBE] rounded">
                                                            {badge.ticker}
                                                        </span>
                                                    );
                                                }
                                                if (badge.kind === 'mentioned') {
                                                    return (
                                                        <span className="px-2 py-0.5 bg-gray-700/40 text-gray-400 rounded">
                                                            Menciona {badge.ticker}
                                                        </span>
                                                    );
                                                }
                                                return (
                                                    <span className="px-2 py-0.5 bg-gray-700/40 text-gray-400 rounded">
                                                        Mercado general
                                                    </span>
                                                );
                                            })()}
                                        </div>
                                    </div>
                                </div>
                            </a>
                        ))}
                    </div>
                )}
            </section>
    );
}

