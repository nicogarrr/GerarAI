import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';

import BackendOffline from '@/components/system/BackendOffline';
import { ScreenBreadcrumbName } from '@/components/screeners/ScreenBreadcrumbName';
import { getKnowledgeDocument, getKnowledgeDocumentChunkPage, getKnowledgeLetters } from '@/lib/actions/research-tools.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';

import { LibraryChat } from '../../_components/LibraryChat';
import { Pagination } from '../../_components/Pagination';
import { investorLetters } from '../investor-letters';
import { authorKey, groupLetters, letterNeighbors, titleYear, type LetterNeighbors } from '../letters';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
    title: 'Leer carta',
    description: 'Texto de una carta a inversores, por fragmentos, con enlace al PDF original.',
};

const PAGE_SIZE = 8;
const LINK = 'text-sm text-teal-300 hover:underline';

type PageProps = {
    params: Promise<{ id: string }>;
    searchParams: Promise<{ pagina?: string; inversor?: string }>;
};

export default async function LetterReaderPage({ params, searchParams }: PageProps) {
    const { id } = await params;
    const { pagina, inversor } = await searchParams;
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
            return <BackendOffline feature="Carta" retryHref={`/inversores/cartas/${letterId}`} />;
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
                    Volver a las cartas{author ? ` de ${author}` : ''}
                </Link>
                <h1 className="text-2xl font-semibold text-gray-100 sm:text-3xl">{letter.title}</h1>
                <p className="text-sm text-gray-400">
                    {author ?? 'Autor no registrado'}
                    {' · '}
                    {letter.publication_date
                        ? `Publicada el ${letter.publication_date}`
                        : `Fecha de publicación no registrada${year ? ` · el título indica ${year}` : ''}`}
                </p>
                {letter.source_url ? (
                    <a className={LINK} href={letter.source_url} rel="noreferrer" target="_blank">
                        Abrir el PDF original
                    </a>
                ) : (
                    <span className="text-xs text-gray-500">Sin PDF original</span>
                )}
                {/* El Cerebro queda abajo a la derecha, plegado; este botón lo abre ya
                    centrado en esta carta. */}
                <LibraryChat scope="letters" authors={author ? [author] : []} documentId={letterId} documentTitle={letter.title} label="Preguntar sobre esta carta" className="self-start" />
            </header>

            {chunks.length === 0 ? (
                <p className="text-sm text-gray-500">Esta carta no tiene texto extraído en la biblioteca. Abre el PDF original.</p>
            ) : (
                <section aria-label="Texto de la carta" className="flex flex-col gap-4">
                    {chunks.map((chunk) => (
                        <article className="rounded-2xl border border-gray-800 bg-surface-1 p-4 sm:p-5" id={`chunk-${chunk.id}`} key={chunk.id}>
                            <p className="mb-2 text-xs text-gray-500">
                                Fragmento {Number(chunk.chunk_index) + 1}
                                {chunk.page_number === null || chunk.page_number === undefined ? '' : ` · página ${chunk.page_number}`}
                            </p>
                            <p className="whitespace-pre-wrap break-words text-sm leading-7 text-gray-300">{chunk.content}</p>
                        </article>
                    ))}
                </section>
            )}

            <Pagination basePath={`/inversores/cartas/${letterId}`} page={page} total={totalPages} params={verifiedInvestor ? { inversor: verifiedInvestor } : {}} />

            {neighbors.older || neighbors.newer ? (
                <nav aria-label={`Más cartas${author ? ` de ${author}` : ''}`} className="grid gap-3 border-t border-gray-800 pt-4 sm:grid-cols-2">
                    {neighbors.older ? (
                        <Link className="flex min-h-11 flex-col justify-center rounded-lg border border-gray-800 px-4 py-3 hover:border-teal-400/40" href={`/inversores/cartas/${neighbors.older.id}`}>
                            <span className="text-xs text-gray-500">← Carta anterior</span>
                            <span className="text-sm text-gray-200">{neighbors.older.title}</span>
                        </Link>
                    ) : <span className="hidden sm:block" />}
                    {neighbors.newer ? (
                        <Link className="flex min-h-11 flex-col justify-center rounded-lg border border-gray-800 px-4 py-3 text-right hover:border-teal-400/40" href={`/inversores/cartas/${neighbors.newer.id}`}>
                            <span className="text-xs text-gray-500">Carta siguiente →</span>
                            <span className="text-sm text-gray-200">{neighbors.newer.title}</span>
                        </Link>
                    ) : null}
                </nav>
            ) : null}

            <p className="text-xs text-gray-500">
                Fuente: biblioteca de GerarAI, texto extraído del PDF y troceado en fragmentos (puede tener errores de extracción;
                el PDF original manda). Es doctrina de inversión, no datos de las empresas.
            </p>
        </main>
        </div>
    );
}
