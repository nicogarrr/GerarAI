import type { Metadata } from 'next';
import Link from 'next/link';
import AlertsManager from '@/components/alerts/AlertsManager';
import EmailNotifications from '@/components/alerts/EmailNotifications';
import PushNotifications from '@/components/alerts/PushNotifications';
import { PageHeader } from '@/components/ui/page-header';
import { getT } from '@/lib/i18n/server';
import { i18nPageMetadata } from '@/lib/i18n/metadata';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function generateMetadata(): Promise<Metadata> {
    return i18nPageMetadata('alerts.meta.title', 'alerts.meta.description');
}

export default async function AlertsPage() {
    const ti = await getT();
    return (
        <main id="content" tabIndex={-1} className="mx-auto flex w-full max-w-5xl flex-col gap-6">
            <PageHeader
                title={ti('alerts.header.title')}
                actions={<Link href="/calendar/resultados" className="inline-flex min-h-11 items-center text-sm text-gray-400 transition-colors hover:text-teal-200">{ti('alerts.header.resultsLink')}</Link>}
            />

            <PushNotifications />

            <EmailNotifications />

            <AlertsManager />
        </main>
    );
}
