import type { Metadata } from 'next';
import Link from 'next/link';

import { getT } from '@/lib/i18n/server';

export async function generateMetadata(): Promise<Metadata> {
    const t = await getT();
    return { title: t('investors.learn.metaTitle'), description: t('investors.learn.description') };
}

export default async function AprenderPage() {
    const t = await getT();
    // cartas y vídeos pasan a la ficha de cada inversor.
    const SECTIONS = [
        { href: '/inversores/conceptos', title: t('investors.learn.concepts'), text: t('investors.learn.conceptsText') },
        { href: '/inversores/canales', title: t('investors.learn.channels'), text: t('investors.learn.channelsText') },
    ];
    return (
        <main className="mx-auto flex w-full min-w-0 max-w-5xl flex-col gap-6 overflow-x-clip py-6" id="content" tabIndex={-1}>
            <header className="flex flex-col gap-1">
                <h1 className="text-xl font-bold text-gray-100 sm:text-2xl">{t('investors.learn.title')}</h1>
                <p className="text-base text-gray-400">{t('investors.learn.description')}</p>
            </header>
            <ul className="grid gap-3 sm:grid-cols-2">
                {SECTIONS.map((section) => (
                    <li key={section.href}>
                        <Link
                            className="flex h-full flex-col gap-1 rounded-2xl border border-gray-800 bg-surface-1 p-6 transition-colors hover:border-gray-700"
                            href={section.href}
                        >
                            <span className="text-base font-medium text-gray-100">{section.title}</span>
                            <span className="text-sm text-gray-400">{section.text}</span>
                        </Link>
                    </li>
                ))}
            </ul>
        </main>
    );
}
