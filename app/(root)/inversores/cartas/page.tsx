import type { Metadata } from 'next';
import Link from 'next/link';

import BackendOffline from '@/components/system/BackendOffline';
import { getKnowledgeLetters } from '@/lib/actions/research-tools.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';

import { IngestLettersButton } from '../_components/IngestLettersButton';
import { LibraryChat } from '../_components/LibraryChat';
import { Pagination, paginate } from '../_components/Pagination';
import { groupLetters, titleYear } from './letters';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
    title: 'Cartas de inversores',
    description: 'Las cartas a inversores de la biblioteca, por autor, con enlace al PDF original.',
};

const PAGE_SIZE = 12;
const LINK = 'text-sm text-teal-300 hover:underline';

type PageProps = {
    searchParams: Promise<{ autor?: string; pagina?: string }>;
};

export default async function LettersPage({ searchParams }: PageProps) {
    const { autor, pagina } = await searchParams;
    let documents: Awaited<ReturnType<typeof getKnowledgeLetters>>;
    try {
        documents = await getKnowledgeLetters();
    } catch (error) {
        if (isBackendUnavailableError(error)) {
            return <BackendOffline feature="Cartas de inversores" retryHref="/inversores/cartas" />;
        }
        throw error;
    }
    const groups = groupLetters(documents);
    const selected = groups.find((group) => group.key === autor) ?? groups[0];
    const paged = selected ? paginate(selected.letters, pagina, PAGE_SIZE) : null;

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex w-full min-w-0 max-w-5xl flex-col gap-5 overflow-x-clip py-6">
            <header className="flex items-center justify-between gap-3">
                <h1 className="text-xl font-semibold text-gray-100 sm:text-2xl">Cartas</h1>
                <Link className={LINK} href="/inversores">
                    Volver a inversores
                </Link>
            </header>
            {groups.length > 0 ? (
                <LibraryChat authors={groups.filter(group => group.name !== 'Sin autor').map(group => group.name)} label="Preguntar a las cartas" className="self-start" />
            ) : null}


            {groups.length === 0 || !selected || !paged ? (
                <div className="flex flex-col items-center gap-4 rounded-2xl border border-gray-800 bg-surface-1 p-8 text-center">
                    <p className="text-sm text-gray-500">Todavía no hay cartas en la biblioteca.</p>
                    <IngestLettersButton />
                </div>
            ) : (
                <>
                    <details className="rounded-lg border border-gray-800 bg-surface-1">
                        <summary className="cursor-pointer px-4 py-3 text-sm text-gray-200">
                            {selected.name} · {selected.letters.length} cartas
                        </summary>
                        <ul className="grid gap-1 border-t border-gray-800 p-2 sm:grid-cols-2">
                            {groups.map((group) => (
                                <li key={group.key}>
                                    <Link
                                        aria-current={group.key === selected.key ? 'page' : undefined}
                                        className={`flex min-h-11 items-center justify-between gap-3 rounded-md px-3 py-2 text-sm ${group.key === selected.key ? 'bg-teal-300/10 text-teal-300' : 'text-gray-300 hover:bg-gray-800'}`}
                                        href={`/inversores/cartas?autor=${group.key}`}
                                        scroll={false}
                                    >
                                        <span>{group.name}</span>
                                        <span className="text-xs text-gray-500">{group.letters.length}</span>
                                    </Link>
                                </li>
                            ))}
                        </ul>
                    </details>

                    <section className="flex flex-col gap-3">
                        <h2 className="text-xl font-semibold text-gray-100">{selected.name}</h2>
                        <ul className="flex flex-col divide-y divide-gray-900">
                            {paged.items.map((letter) => {
                                const year = titleYear(letter.title);
                                return (
                                    <li className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-3" key={letter.id}>
                                        <Link className="min-w-0 text-sm text-gray-200 hover:text-teal-200 hover:underline" href={`/inversores/cartas/${letter.id}`}>{letter.title}</Link>
                                        <span className="flex items-center gap-4">
                                            <Link className={LINK} href={`/inversores/cartas/${letter.id}`}>
                                                Leer
                                            </Link>
                                            {letter.source_url ? (
                                                <a className={LINK} href={letter.source_url} rel="noreferrer" target="_blank">
                                                    PDF original
                                                </a>
                                            ) : (
                                                <span className="text-xs text-gray-500">Sin PDF original</span>
                                            )}
                                        </span>
                                        <span className="w-full text-xs text-gray-500">
                                            {letter.publication_date
                                                ? `Publicada el ${letter.publication_date}`
                                                : 'Fecha de publicación no registrada'}
                                            {year && !letter.publication_date ? ` · el título indica ${year}` : ''}
                                        </span>
                                    </li>
                                );
                            })}
                        </ul>
                    </section>

                    <Pagination basePath="/inversores/cartas" page={paged.page} params={{ autor: selected.key }} total={paged.total} />
                </>
            )}

            <p className="text-xs text-gray-500">
                Fuente: biblioteca de GerarAI. Las cartas son doctrina de inversión, no datos de las empresas. Si no hay fecha de
                publicación registrada se dice; el año del título es solo una pista.
            </p>
        </main>
    );
}
