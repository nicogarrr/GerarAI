'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { BrainGlassesIcon } from '@/components/brain/BrainGlassesIcon';
import { MOBILE_TAB_ITEMS, isNavItemActive, isNavItemExact } from '@/lib/constants';
import { useT } from '@/lib/i18n/client';

/**
 * Barra inferior del movil: cinco destinos con etiqueta y el Cerebro como
 * boton central de la misma rejilla (antes era una franja apilada encima que
 * pisaba la barra y duplicaba su altura; sigue tambien en el menu hamburguesa).
 * Solo por debajo de `md`; en escritorio manda la barra lateral.
 */
export default function BottomNav() {
    const pathname = usePathname();
    const t = useT();
    const middle = Math.ceil(MOBILE_TAB_ITEMS.length / 2);
    const items: Array<(typeof MOBILE_TAB_ITEMS)[number] | 'cerebro'> = [
        ...MOBILE_TAB_ITEMS.slice(0, middle),
        'cerebro',
        ...MOBILE_TAB_ITEMS.slice(middle),
    ];

    return (
        <nav
            aria-label={t('shell.nav.bottomAria')}
            data-bottom-nav
            className="fixed inset-x-0 bottom-0 z-40 border-t border-gray-800 bg-gray-950/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
        >
            <ul className="mx-auto grid max-w-md grid-cols-6">
                {items.map((item) => {
                    if (item === 'cerebro') {
                        return (
                            <li key="cerebro">
                                <button
                                    aria-label={t('brain.openAria')}
                                    className="flex min-h-14 w-full flex-col items-center justify-center gap-0.5 text-[11px] font-medium text-teal-300 transition-colors hover:text-teal-200"
                                    onClick={() => window.dispatchEvent(new Event('gerarai:open-brain'))}
                                    type="button"
                                >
                                    <BrainGlassesIcon aria-hidden="true" className="h-5 w-5" />
                                    <span>{t('brain.name')}</span>
                                </button>
                            </li>
                        );
                    }
                    const active = isNavItemActive(pathname, item.href);
                    return (
                        <li key={item.href}>
                            <Link
                                href={item.href}
                                aria-current={active ? (isNavItemExact(pathname, item.href) ? 'page' : 'true') : undefined}
                                className={`flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] font-medium transition-colors ${
                                    active ? 'text-teal-300' : 'text-gray-500 hover:text-gray-300'
                                }`}
                            >
                                <item.icon aria-hidden="true" className="h-5 w-5" />
                                <span>{t(item.labelKey)}</span>
                            </Link>
                        </li>
                    );
                })}
            </ul>
        </nav>
    );
}
