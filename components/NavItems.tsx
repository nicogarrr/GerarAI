'use client'

import IntentLink from '@/components/layout/IntentLink'
import {usePathname} from 'next/navigation'
import {isNavItemActive, isNavItemExact, NAV_SECTIONS, showsNavSectionTitle, type NavItem} from '@/lib/constants'
import {useT} from '@/lib/i18n/client'

/**
 * Version movil del menu. Comparte arbol, reglas de estado activo y titulos con
 * `components/layout/Sidebar.tsx`; lo unico que cambia son las alturas tactiles
 * (min-h-11) y que aqui no hay version plegable.
 */
const NavItems = () => {
    const pathname = usePathname()
    const t = useT()

    return (
        <ul className="flex max-w-full flex-col p-2 text-sm font-medium">
            {NAV_SECTIONS.map((section) => (
                <li key={section.titleKey}>
                    {showsNavSectionTitle(section) && (
                        <p className="px-1 pb-1 pt-4 text-xs font-semibold uppercase tracking-wide text-gray-400">
                            {section.titleKey ? t(section.titleKey) : null}
                        </p>
                    )}
                    <ul className="flex flex-col gap-1">
                        {section.items.map((item) => (
                            <li className="shrink-0" key={item.href}>
                                <ItemLink item={item} pathname={pathname} />
                            </li>
                        ))}
                    </ul>
                </li>
            ))}
        </ul>
    )
}

function ariaCurrent(active: boolean, exact: boolean): 'page' | 'true' | undefined {
    if (!active) return undefined
    return exact ? 'page' : 'true'
}

function ItemLink({item, pathname}: {item: NavItem; pathname: string}) {
    const t = useT()
    const active = isNavItemActive(pathname, item.href)
    const branchActive = active || (item.children ?? []).some((child) => isNavItemActive(pathname, child.href))

    return (
        <>
            <IntentLink
                href={item.href}
                aria-current={ariaCurrent(active, isNavItemExact(pathname, item.href))}
                className={classes(active, 'text-base', branchActive)}
            >
                {item.icon && <item.icon aria-hidden="true" className="h-4 w-4 shrink-0" />}
                <span className="truncate">{t(item.labelKey)}</span>
            </IntentLink>
            {item.children && (
                <ul className="mt-1 flex flex-col gap-1 border-l border-gray-700/50 pl-3">
                    {item.children.map((child) => {
                        const childActive = isNavItemActive(pathname, child.href)
                        return (
                            <li className="shrink-0" key={child.href}>
                                <IntentLink
                                    href={child.href}
                                    aria-current={ariaCurrent(childActive, isNavItemExact(pathname, child.href))}
                                    className={classes(childActive, 'text-base')}
                                >
                                    <span className="truncate">{t(child.labelKey)}</span>
                                </IntentLink>
                            </li>
                        )
                    })}
                </ul>
            )}
        </>
    )
}

/** Mismo tratamiento activo que en desktop: barra teal, no solo un fondo. */
function classes(active: boolean, size = 'text-base', branch = false) {
    return [
        'relative flex min-h-11 items-center gap-2 rounded-lg px-2 py-2 transition-colors',
        size,
        active
            ? 'bg-gray-800/70 text-gray-100 before:absolute before:inset-y-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-teal-400'
            : branch
              // Rama con la pagina actual debajo: texto claro sin fondo ni
              // barra; el padre no es un segundo destino activo (F283).
              ? 'text-gray-100 hover:bg-gray-800/70 hover:text-teal-300'
              : 'text-gray-400 hover:bg-gray-800/70 hover:text-teal-300',
    ].join(' ')
}

export default NavItems
