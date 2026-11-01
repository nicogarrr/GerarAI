import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';

import BackendOffline from '@/components/system/BackendOffline';
import { ScreenBreadcrumbName } from '@/components/screeners/ScreenBreadcrumbName';
import { getKnowledgeDocument, getKnowledgeDocumentChunkPage, getKnowledgeLetters } from '@/lib/actions/research-tools.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { getT } from '@/lib/i18n/server';

import { LibraryChat } from '../../_components/LibraryChat';
import { Pagination } from '../../_components/Pagination';
import { investorLetters } from '../investor-letters';
import { authorKey, groupLetters, letterNeighbors, titleYear, type LetterNeighbors } from '../letters';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function generateMetadata(): Promise<Metadata> {
    const t = await getT();
    return { title: t('investors.reader.metaTitle'), description: t('investors.reader.metaDescription') };
}

const PAGE_SIZE = 8;
const LINK = 'text-sm text-teal-300 hover:underline';

type PageProps = {
    params: Promise<{ id: string }>;
    searchParams: Promise<{ pagina?: string; inversor?: string }>;
};

export default async function LetterReaderPage({ params, searchParams }: PageProps) {
    const { id } = await params;
    const { pagina, inversor } = await searchParams;
    const t = await getT();
    const letterId = /^\d+$/.test(id) ? Number(id) : null;
    if (!letterId) notFound();

    let letter: Awaited<ReturnType<typeof getKnowledgeDocument>>;
    let chunks: Awaited<ReturnType<typeof getKnowledgeDocumentChunkPage>> = [];
    let page = 1;
    let totalPages = 1;
    try {
        letter = await getKnowledgeDocument(letterId);
        if (!letter || letter.document_type !== 'fund_letter') notFound();
        totalPages = Math.max(1, Math.ceil(letter.chunk_count / PAGE_SIZE));
        const parsed = Number.parseInt(pagina ?? '1', 10);
        page = Number.isFinite(parsed) ? Math.min(Math.max(1, parsed), totalPages) : 1;
        if (letter.chunk_count > 0) chunks = await getKnowledgeDocumentChunkPage(letterId, (page - 1) * PAGE_SIZE, PAGE_SIZE);
    } catch (error) {
        if (isBackendUnavailableError(error)) {
            return <BackendOffline feature={t('investors.reader.offline')} retryHref={`/inversores/cartas/${letterId}`} />;
        }
        throw error;
    }

    const year = titleYear(letter.title);
    const author = letter.author?.trim() || null;
    // Seguir leyendo sin volver a la lista: carta anterior/siguiente del mismo
    // autor. Es un extra: si falla la lista de cartas, la carta se lee igual.
    let neighbors: LetterNeighbors = { older: null, newer: null };
    try {
        neighbors = letterNeighbors(groupLetters(await getKnowledgeLetters()), letterId);
    } catch {
        neighbors = { older: null, newer: null };
    }
    const verifiedInvestor = inversor && investorLetters(inversor, [letter]).length > 0 ? inversor : null;
    const backHref = verifiedInvestor ? `/inversores/${encodeURIComponent(verifiedInvestor)}?vista=cartas` : author ? `/inversores/cartas?autor=${authorKey(author) || 'sin-autor'}` : '/inversores/cartas?autor=sin-autor';

    return (
        <div className="min-w-0">
        {/* Miga con el titulo real: sin el override la ruta muestra el id crudo. */}
        <ScreenBreadcrumbName name={letter.title} />
        <main id="content" tabIndex={-1} className="mx-auto flex w-full min-w-0 max-w-3xl flex-col gap-8 overflow-x-clip py-6">
            <header className="flex flex-col gap-3">
                <Link className={LINK} href={backHref}>
                    {author ? t('investors.reader.backOf', { author }) : t('investors.reader.back')}
                </Link>
                <h1 className="text-2xl font-semibold text-gray-100 sm:text-3xl">{letter.title}</h1>
                <p className="text-sm text-gray-400">
                    {author ?? t('investors.reader.noAuthor')}
                    {' · '}
                    {letter.publication_date
                        ? t('investors.letters.publishedOn', { date: letter.publication_date })
                        : `${t('investors.letters.noPublicationDate')}${year ? ` · ${t('investors.letters.titleSays', { year })}` : ''}`}
                </p>
                {letter.source_url ? (
                    <a className={LINK} href={letter.source_url} rel="noreferrer" target="_blank">
                        {t('investors.reader.openPdf')}
                    </a>
                ) : (
                    <span className="text-xs text-gray-500">{t('investors.letters.noPdf')}</span>
                )}
                {/* El Cerebro queda abajo a la derecha, plegado; este botón lo abre ya
                    centrado en esta carta. */}
                <LibraryChat scope="letters" authors={author ? [author] : []} documentId={letterId} documentTitle={letter.title} label={t('investors.reader.ask')} className="self-start" />
            </header>

            {chunks.length === 0 ? (
                <p className="text-sm text-gray-500">{t('investors.reader.noText')}</p>
            ) : (
                <section aria-label={t('investors.reader.textAria')} className="flex flex-col gap-4">
                    {chunks.map((chunk) => (
                        <article className="rounded-2xl border border-gray-800 bg-surface-1 p-4 sm:p-5" id={`chunk-${chunk.id}`} key={chunk.id}>
                            <p className="mb-2 text-xs text-gray-500">
                                {t('investors.reader.excerpt', { n: Number(chunk.chunk_index) + 1 })}
                                {chunk.page_number === null || chunk.page_number === undefined ? '' : ` · ${t('investors.reader.page', { n: chunk.page_number })}`}
                            </p>
                            <p className="whitespace-pre-wrap break-words text-sm leading-7 text-gray-300">{chunk.content}</p>
                        </article>
                    ))}
                </section>
            )}

            <Pagination basePath={`/inversores/cartas/${letterId}`} page={page} total={totalPages} params={verifiedInvestor ? { inversor: verifiedInvestor } : {}} />

            {neighbors.older || neighbors.newer ? (
                <nav aria-label={author ? t('investors.reader.moreOf', { author }) : t('investors.reader.more')} className="grid gap-3 border-t border-gray-800 pt-4 sm:grid-cols-2">
                    {neighbors.older ? (
                        <Link className="flex min-h-11 flex-col justify-center rounded-lg border border-gray-800 px-4 py-3 hover:border-teal-400/40" href={`/inversores/cartas/${neighbors.older.id}`}>
                            <span className="text-xs text-gray-500">{t('investors.reader.older')}</span>
                            <span className="text-sm text-gray-200">{neighbors.older.title}</span>
                        </Link>
                    ) : <span className="hidden sm:block" />}
                    {neighbors.newer ? (
                        <Link className="flex min-h-11 flex-col justify-center rounded-lg border border-gray-800 px-4 py-3 text-right hover:border-teal-400/40" href={`/inversores/cartas/${neighbors.newer.id}`}>
                            <span className="text-xs text-gray-500">{t('investors.reader.newer')}</span>
                            <span className="text-sm text-gray-200">{neighbors.newer.title}</span>
                        </Link>
                    ) : null}
                </nav>
            ) : null}

            <p className="text-xs text-gray-500">
                {t('investors.reader.source')}
            </p>
        </main>
        </div>
    );
}
