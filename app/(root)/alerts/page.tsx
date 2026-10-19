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
            <header className="border-b border-gray-800 pb-5">
                <p className="text-sm font-semibold uppercase text-teal-300">Notificaciones</p>
                <h1 className="mt-1 text-2xl font-bold text-gray-100 sm:text-3xl">Alertas</h1>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-400">
                    Configura alertas en tiempo real sobre precios, noticias y resultados de tus acciones.{' '}
                    <Link href="/calendar" className="text-teal-300 underline decoration-gray-700 underline-offset-4 hover:text-teal-200">
                        Ver el calendario de resultados
                    </Link>
                    .
                </p>
            </header>

            <AlertsManager />
        </main>
    );
}
