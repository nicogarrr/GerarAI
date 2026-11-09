import type { Metadata } from 'next';
import ExportView from '@/components/export/ExportView';
import ObsidianVaultCard from '@/components/export/ObsidianVaultCard';
import { getT } from '@/lib/i18n/server';
import { i18nPageMetadata } from '@/lib/i18n/metadata';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function generateMetadata(): Promise<Metadata> {
    return i18nPageMetadata('export.meta.title', 'export.meta.description');
}

export default async function ExportPage() {
    const t = await getT();
    return (
        <main id="content" tabIndex={-1} className="mx-auto flex max-w-6xl flex-col gap-6">
            <header className="flex flex-col gap-3 border-b border-gray-800 pb-5 lg:flex-row lg:items-end lg:justify-between">
                <div>
                    <p className="text-sm font-semibold uppercase text-teal-300">{t('export.header.eyebrow')}</p>
                    <h1 className="mt-1 text-3xl font-bold text-gray-100">{t('export.header.title')}</h1>
                </div>
            </header>

            <ExportView />

            <ObsidianVaultCard />
        </main>
    );
}
