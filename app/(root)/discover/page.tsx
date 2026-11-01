import type { Metadata } from 'next';
import Link from 'next/link';
import { ArrowUpRight } from 'lucide-react';
import { flattenNavItems } from '@/lib/constants';
import { getT } from '@/lib/i18n/server';

// Las tarjetas se derivan del ROUTE_CATALOG (items con hub '/discover' y
// descripcion): una sola fuente. Antes la pagina mantenia su propia lista y se
// quedaba sin /ownership mientras el subnav si lo tenia.
const tools = flattenNavItems().filter(
  (item) => item.hub === '/discover' && item.href !== '/discover' && item.descriptionKey,
);

export async function generateMetadata(): Promise<Metadata> {
  const t = await getT();
  return { title: t('discover.metaTitle') };
}

export default async function Discover(){const t = await getT(); return <main id="content" className="mx-auto max-w-6xl"><header className="mb-8"><p className="mb-2 text-xs font-semibold uppercase tracking-widest text-teal-400">{t('discover.kicker')}</p><h1 className="text-3xl font-semibold text-gray-100">{t('discover.title')}</h1></header><div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{tools.map(({href,labelKey,descriptionKey,icon:Icon})=><Link key={href} href={href} className="group rounded-xl border border-gray-800 bg-gray-900/40 p-5 transition-colors hover:border-teal-400/40 hover:bg-gray-900"><div className="mb-5 flex items-center justify-between"><Icon aria-hidden="true" className="h-5 w-5 text-teal-400"/><ArrowUpRight aria-hidden="true" className="h-4 w-4 text-gray-600 group-hover:text-teal-300"/></div><h2 className="text-lg font-medium text-gray-100">{t(labelKey)}</h2><p className="mt-2 text-sm leading-relaxed text-gray-400">{descriptionKey ? t(descriptionKey) : null}</p></Link>)}</div></main>}
