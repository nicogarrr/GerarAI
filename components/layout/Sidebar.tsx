'use client';

import { useState } from 'react';
import IntentLink from '@/components/layout/IntentLink';
import { usePathname } from 'next/navigation';
import { ChevronsLeft, ChevronsRight } from 'lucide-react';
import { isNavItemActive, isNavItemExact, NAV_SECTIONS, showsNavSectionTitle, type NavItem } from '@/lib/constants';

import { SIDEBAR_COLLAPSED_COOKIE } from '@/lib/ui/sidebar-preference';
import { useT } from '@/lib/i18n/client';

/**
 * Navegacion de escritorio. Complementa a `components/MobileNav.tsx`, que usa
 * el mismo arbol de `NAV_SECTIONS`: los breakpoints son los mismos (`md`) para
 * que entre 640px y 767px no quede ninguna ventana sin navegacion primaria.
 *
 * Alturas y anchuras vienen de --shell-top / --sidebar-w (globals.css). El
 * aside se ancla a `top: --shell-top` con alto `100dvh - --shell-top` (con
 * `h-dvh` a secas el pie quedaba bajo el fold a scroll 0) y la zona pegajosa
 * con `pt`: asi el borde superior nunca queda escondido bajo el header, y lo
 * mismo vale cuando el aviso de "sin conexion" aniade su propia altura.
 */
export default function Sidebar({ collapsed: initiallyCollapsed }: { collapsed: boolean }) {
    const pathname = usePathname();
    const t = useT();
    const [collapsed, setCollapsed] = useState(initiallyCollapsed);

    const toggle = () => {
        setCollapsed((prev) => {
            const next = !prev;
            document.cookie = `${SIDEBAR_COLLAPSED_COOKIE}=${next ? '1' : '0'};path=/;max-age=31536000;samesite=lax`;
            return next;
        });
    };

    return (
        <aside
            data-collapsed={collapsed || undefined}
            className="sticky top-[var(--shell-top)] z-10 hidden h-[calc(100dvh-var(--shell-top))] shrink-0 flex-col border-r border-gray-700/50 bg-gray-900 transition-[width] duration-200 md:flex data-[collapsed]:w-[var(--sidebar-w-collapsed)] w-[var(--sidebar-w)]"
        >
            <button
                onClick={toggle}
                title={collapsed ? t('shell.menu.expand') : t('shell.menu.collapse')}
                aria-label={collapsed ? t('shell.menu.expand') : t('shell.menu.collapse')}
                aria-expanded={!collapsed}
                className="m-2 flex h-9 w-fit items-center justify-center rounded-lg text-gray-300 hover:bg-gray-800 hover:text-teal-300"
            >
                {collapsed ? <ChevronsRight aria-hidden="true" className="h-5 w-5" /> : <ChevronsLeft aria-hidden="true" className="h-5 w-5" />}
            </button>

            <nav
                className="scrollbar-hide-default min-h-0 flex-1 overflow-y-auto px-2 pb-4"
                aria-label={t('shell.nav.primaryAria')}
            >
                <ul className="flex flex-col">
                    {NAV_SECTIONS.map((section) => {
                        const showTitle = showsNavSectionTitle(section);
                        return (
                            <li key={section.titleKey ?? section.items[0]?.href}>
                                {showTitle && (
                                    collapsed ? (
                                        <div className="mx-2 my-3 border-t border-gray-700/50" aria-hidden="true" />
                                    ) : (
                                        <p className="px-3 pb-1 pt-4 text-xs font-semibold uppercase tracking-wide text-gray-500">
                                            {section.titleKey ? t(section.titleKey) : null}
                                        </p>
                                    )
                                )}
                                <ul className="flex flex-col gap-1">
                                    {section.items.map((item) => (
                                        <li key={item.href}>
                                            <NavLink item={item} pathname={pathname} collapsed={collapsed} />
                                        </li>
                                    ))}
                                </ul>
                            </li>
                        );
                    })}
                </ul>
            </nav>

        </aside>
    );
}

function ariaCurrent(active: boolean, exact: boolean): 'page' | 'true' | undefined {
    if (!active) return undefined;
    return exact ? 'page' : 'true';
}

function NavLink({ item, pathname, collapsed }: { item: NavItem; pathname: string; collapsed: boolean }) {
    const t = useT();
    const active = isNavItemActive(pathname, item.href);
    // Un padre se ilumina cuando la ruta cae en un hijo suyo, para que la
    // rama "Research" siga visible dentro de /research/news.
    const branchActive = active || (item.children ?? []).some((child) => isNavItemActive(pathname, child.href));

    return (
        <>
            <IntentLink
                href={item.href}
                aria-label={t(item.labelKey)}
                title={collapsed ? t(item.labelKey) : undefined}
                aria-current={ariaCurrent(active, isNavItemExact(pathname, item.href))}
                className={linkClasses(active, collapsed, 'text-sm', branchActive)}
            >
                {item.icon && <item.icon aria-hidden="true" className="h-4 w-4 shrink-0" />}
                {!collapsed && <span className="truncate">{t(item.labelKey)}</span>}
            </IntentLink>
            {item.children && (
                <ul className={collapsed ? "mt-1 flex flex-col gap-1" : "mt-1 flex flex-col gap-1 border-l border-gray-700/50 pl-3"}>
                    {item.children.map((child) => {
                        const childActive = isNavItemActive(pathname, child.href);
                        return (
                            <li key={child.href}>
                                <IntentLink
                                    href={child.href}
                                    aria-label={t(child.labelKey)}
                                    title={collapsed ? t(child.labelKey) : undefined}
                                    aria-current={ariaCurrent(childActive, isNavItemExact(pathname, child.href))}
                                    className={linkClasses(childActive, collapsed, 'text-sm')}
                                >
                                    {collapsed ? <child.icon aria-hidden="true" className="h-4 w-4 shrink-0" /> : <span className="truncate">{t(child.labelKey)}</span>}
                                </IntentLink>
                            </li>
                        );
                    })}
                </ul>
            )}
        </>
    );
}

/**
 * La barra teal del item activo se dibuja con un pseudo-elemento en vez de con
 * `border-l-2`: un borde real cambia el ancho de la caja al alternar estados
 * y hace que el redondeo se corte en la esquina.
 */
function linkClasses(active: boolean, collapsed: boolean, extra = 'text-sm', branch = false) {
    return [
        'relative flex items-center gap-3 rounded-lg px-3 py-2 transition-colors',
        extra,
        collapsed ? 'justify-center' : '',
        active
            ? 'bg-gray-800 text-gray-100 before:absolute before:inset-y-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-teal-400'
            : branch
              // La rama contiene la pagina actual, pero el padre NO es la
              // pagina: texto claro sin fondo ni barra, para que no parezca
              // un segundo destino activo (F283).
              ? 'text-gray-100 hover:bg-gray-800 hover:text-teal-300'
              : 'text-gray-400 hover:bg-gray-800 hover:text-teal-300',
    ].join(' ');
}
