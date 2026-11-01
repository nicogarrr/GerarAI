import type { Metadata } from 'next';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';

import { getLocale, getT } from '@/lib/i18n/server';

import { INVESTOR_CHANNELS, channelNoteLabel, channelSourceLabel, type ChannelCategory } from './channels';

export async function generateMetadata(): Promise<Metadata> {
    const t = await getT();
    return { title: t('investors.channels.title'), description: t('investors.channels.description') };
}

export default async function ChannelsPage() {
    const t = await getT();
    const locale = await getLocale();
    const SECTIONS: { category: ChannelCategory; title: string }[] = [
        { category: 'inversion', title: t('investors.channels.sectionInversion') },
        { category: 'negocio', title: t('investors.channels.sectionNegocio') },
        { category: 'referencia', title: t('investors.channels.sectionReferencia') },
        { category: 'empresa', title: t('investors.channels.sectionEmpresa') },
    ];
    return (
        <main id="content" tabIndex={-1} className="mx-auto flex w-full min-w-0 max-w-5xl flex-col gap-8 overflow-x-clip py-6">
            <Link
                className="inline-flex items-center gap-2 text-sm text-teal-300 hover:underline"
                href="/inversores/aprender"
            >
                <ArrowLeft aria-hidden="true" className="h-4 w-4" />
                {t('investors.channels.back')}
            </Link>
            <header className="flex flex-col gap-3">
                <h1 className="text-3xl font-semibold text-gray-100">{t('investors.channels.title')}</h1>
            </header>
            {SECTIONS.map((section) => {
                const items = INVESTOR_CHANNELS.filter((channel) => channel.category === section.category);
                return (
                    <section className="flex flex-col gap-3" key={section.category}>
                        <h2 className="text-xl font-semibold text-gray-100">{section.title}</h2>
                        <ul className="flex flex-col divide-y divide-gray-900">
                            {items.map((channel) => (
                                <li className="flex flex-col gap-1 py-3" key={channel.url}>
                                    <a
                                        className="text-base font-medium text-gray-100 underline-offset-2 hover:underline"
                                        href={channel.url}
                                        rel="noreferrer"
                                        target="_blank"
                                    >
                                        {channel.name}
                                    </a>
                                    <p className="text-xs text-gray-500">
                                        {channel.handle} · {channel.language === 'es' ? t('investors.channels.spanish') : t('investors.channels.english')} · {channelSourceLabel(channel.source, locale)}
                                        {channel.note ? ` · ${channelNoteLabel(channel.note, locale)}` : ''}
                                    </p>
                                </li>
                            ))}
                        </ul>
                    </section>
                );
            })}
        </main>
    );
}
