'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { BrainGlassesIcon } from '@/components/brain/BrainGlassesIcon';
import { MOBILE_TAB_ITEMS, isNavItemActive } from '@/lib/constants';

/**
 * Barra inferior del movil: cinco iconos con etiqueta, el destino activo en el
 * color de acento. Solo por debajo de `md`; en escritorio manda la barra lateral.
 */
export default function BottomNav() {
    const pathname = usePathname();

    return (
        <nav
            aria-label="Navegación inferior"
            className="fixed inset-x-0 bottom-0 z-40 border-t border-gray-800 bg-gray-950/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
        >
            <button type="button" onClick={() => window.dispatchEvent(new Event('gerarai:open-brain'))}
                aria-label="Abrir el cerebro" className="flex min-h-11 w-full items-center justify-center gap-2 border-b border-gray-800 text-sm font-medium text-teal-300">
                <BrainGlassesIcon className="h-6 w-6" />Cerebro
            </button>
            <ul className="mx-auto grid max-w-md grid-cols-5">
                {MOBILE_TAB_ITEMS.map((item) => {
                    const active = isNavItemActive(pathname, item.href);
                    return (
                        <li key={item.href}>
                            <Link
                                href={item.href}
                                aria-current={active ? 'page' : undefined}
                                className={`flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] font-medium transition-colors ${
                                    active ? 'text-teal-300' : 'text-gray-500 hover:text-gray-300'
                                }`}
                            >
                                <item.icon aria-hidden="true" className="h-5 w-5" />
                                <span>{item.label}</span>
                            </Link>
                        </li>
                    );
                })}
            </ul>
        </nav>
    );
}
