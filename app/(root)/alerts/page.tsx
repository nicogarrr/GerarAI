import type { Metadata } from 'next';
import Link from 'next/link';
import AlertsManager from '@/components/alerts/AlertsManager';
import PushNotifications from '@/components/alerts/PushNotifications';
import { PageHeader } from '@/components/ui/page-header';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
    title: 'Alertas',
    description:
        'Alertas por precio, cambio, noticias y resultados de tus acciones, con el estado del motor de evaluación y el envío por Telegram.',
};

export default async function AlertsPage() {
    return (
        <main id="content" tabIndex={-1} className="mx-auto flex w-full max-w-5xl flex-col gap-6">
            <PageHeader
                title="Alertas"
                actions={<Link href="/calendar/resultados" className="inline-flex min-h-11 items-center text-sm text-gray-400 transition-colors hover:text-teal-200">Resultados</Link>}
            />

            <PushNotifications />

            <AlertsManager />
        </main>
    );
}
