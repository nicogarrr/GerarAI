import type { Metadata } from 'next';
import Link from 'next/link';
import AlertsManager from '@/components/alerts/AlertsManager';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
    title: 'Alertas',
    description:
        'Alertas por precio, cambio, noticias y resultados de tus acciones, con el estado del motor de evaluación y el envío por Telegram.',
};

export default async function AlertsPage() {
    return (
        <main id="content" tabIndex={-1} className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 py-6 sm:px-6">
            <header className="border-b border-gray-800 pb-4">
                <div className="flex items-center justify-between gap-3">
                    <h1 className="text-xl font-bold text-gray-100 sm:text-2xl">Alertas</h1>
                    <Link href="/calendar" className="text-xs text-gray-400 hover:text-teal-200">Resultados</Link>
                </div>
            </header>

            <AlertsManager />
        </main>
    );
}
