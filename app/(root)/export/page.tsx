import type { Metadata } from 'next';
import ExportView from '@/components/export/ExportView';
import ObsidianVaultCard from '@/components/export/ObsidianVaultCard';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
    title: 'Exportación',
    description: 'Descarga el journal de decisiones de inversión en CSV o JSON, o tus tesis en un vault de Obsidian (.zip).',
};

export default async function ExportPage() {
    return (
        <main id="content" tabIndex={-1} className="mx-auto flex max-w-6xl flex-col gap-6">
            <header className="flex flex-col gap-3 border-b border-gray-800 pb-5 lg:flex-row lg:items-end lg:justify-between">
                <div>
                    <p className="text-sm font-semibold uppercase text-teal-300">Diario</p>
                    <h1 className="mt-1 text-3xl font-bold text-gray-100">Exportación</h1>
                </div>
            </header>

            <ExportView />

            <ObsidianVaultCard />
        </main>
    );
}