import type { Metadata } from 'next';
import Link from 'next/link';

import BackendOffline from '@/components/system/BackendOffline';
import { getKnowledgeLetters } from '@/lib/actions/research-tools.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { getT } from '@/lib/i18n/server';

import { IngestLettersButton } from '../_components/IngestLettersButton';
import { LibraryChat } from '../_components/LibraryChat';
import { Pagination, paginate } from '../_components/Pagination';
import { groupLetters, NO_AUTHOR, titleYear } from './letters';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function generateMetadata(): Promise<Metadata> {
    const t = await getT();
    return { title: t('investors.letters.metaTitle'), description: t('investors.letters.metaDescription') };
}

const PAGE_SIZE = 12;
const LINK = 'text-sm text-teal-300 hover:underline';

type PageProps = {
    searchParams: Promise<{ autor?: string; pagina?: string }>;
};

export default async function LettersPage({ searchParams }: PageProps) {
    const { autor, pagina } = await searchParams;
    const t = await getT();
    let documents: Awaited<ReturnType<typeof getKnowledgeLetters>>;
    try {
        documents = await getKnowledgeLetters();
    } catch (error) {
        if (isBackendUnavailableError(error)) {
            return <BackendOffline feature={t('investors.letters.metaTitle')} retryHref="/inversores/cartas" />;
        }
        throw error;
    }
    const groups = groupLetters(documents);
    const authorName = (name: string) => (name === NO_AUTHOR ? t('investors.letters.noAuthor') : name);
    const selected = groups.find((group) => group.key === autor) ?? groups[0];
    const paged = selected ? paginate(selected.letters, pagina, PAGE_SIZE) : null;

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex w-full min-w-0 max-w-5xl flex-col gap-5 overflow-x-clip py-6">
            <header className="flex items-center justify-between gap-3">
                <h1 className="text-xl font-semibold text-gray-100 sm:text-2xl">{t('investors.letters.title')}</h1>
                <Link className={LINK} href="/inversores">
                    {t('investors.letters.back')}
                </Link>
            </header>
            {groups.length > 0 ? (
                <LibraryChat authors={groups.filter(group => group.name !== NO_AUTHOR).map(group => group.name)} label={t('investors.letters.ask')} className="self-start" />
            ) : null}


            {groups.length === 0 || !selected || !paged ? (
                <div className="flex flex-col items-center gap-4 rounded-2xl border border-gray-800 bg-surface-1 p-8 text-center">
                    <p className="text-sm text-gray-500">{t('investors.letters.empty')}</p>
                    <IngestLettersButton />
                </div>
            ) : (
                <>
                    <details className="rounded-lg border border-gray-800 bg-surface-1">
                        <summary className="cursor-pointer px-4 py-3 text-sm text-gray-200">
                            {authorName(selected.name)} · {t('investors.letters.count', { count: selected.letters.length })}
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
                                        <span>{authorName(group.name)}</span>
                                        <span className="text-xs text-gray-500">{group.letters.length}</span>
                                    </Link>
                                </li>
                            ))}
                        </ul>
                    </details>

                    <section className="flex flex-col gap-3">
                        <h2 className="text-xl font-semibold text-gray-100">{authorName(selected.name)}</h2>
                        <ul className="flex flex-col divide-y divide-gray-900">
                            {paged.items.map((letter) => {
                                const year = titleYear(letter.title);
                                return (
                                    <li className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-3" key={letter.id}>
                                        <Link className="min-w-0 text-sm text-gray-200 hover:text-teal-200 hover:underline" href={`/inversores/cartas/${letter.id}`}>{letter.title}</Link>
                                        <span className="flex items-center gap-4">
                                            <Link className={LINK} href={`/inversores/cartas/${letter.id}`}>
                                                {t('investors.letters.read')}
                                            </Link>
                                            {letter.source_url ? (
                                                <a className={LINK} href={letter.source_url} rel="noreferrer" target="_blank">
                                                    {t('investors.letters.originalPdf')}
                                                </a>
                                            ) : (
                                                <span className="text-xs text-gray-500">{t('investors.letters.noPdf')}</span>
                                            )}
                                        </span>
                                        <span className="w-full text-xs text-gray-500">
                                            {letter.publication_date
                                                ? t('investors.letters.publishedOn', { date: letter.publication_date })
                                                : t('investors.letters.noPublicationDate')}
                                            {year && !letter.publication_date ? ` · ${t('investors.letters.titleSays', { year })}` : ''}
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
                {t('investors.letters.source')}
            </p>
        </main>
    );
}
