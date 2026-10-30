'use client';
import { useT } from '@/lib/i18n/client';

import * as React from 'react';
import { ChevronDown } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import { cn } from '@/lib/utils';

const subscribeHydration = () => () => undefined;

/** `compact` para las vistas densas (terminal financiero, intelligence). */
export type PanelDensity = 'default' | 'compact';

const DENSITY_CLASSES: Record<PanelDensity, { container: string; body: string }> = {
    default: { container: 'p-5', body: 'mt-4' },
    compact: { container: 'p-3', body: 'mt-2' },
};

export interface PanelProps extends Omit<React.HTMLAttributes<HTMLElement>, 'title'> {
    title: string;
    /** Icono junto al titulo: componente lucide o elemento ya pintado. */
    icon?: LucideIcon | React.ReactNode;
    description?: React.ReactNode;
    /** Acciones alineadas a la derecha de la cabecera. */
    actions?: React.ReactNode;
    /**
     * `true` = plegable en cualquier viewport; `"mobile"` = plegable solo por
     * debajo de `md`, que es donde la tabla/documento largo empuja el resto de
     * la pagina. Sin valor, el panel es estatico.
     */
    collapsible?: boolean | 'mobile';
    /** Estado inicial al plegarse (por defecto plegado en movil). */
    defaultOpen?: boolean;
    density?: PanelDensity;
    /** Elemento del titulo; `h2` salvo que la pagina ya tenga ese nivel. */
    titleAs?: 'h2' | 'h3';
}

/**
 * matchMedia reactivo y seguro en SSR: el servidor y la primera pintada del
 * cliente asumen `false` (mobile-first; en desktop el contenido ya se ve por
 * `md:block`), y tras la hidratacion el valor real corrige el estado ARIA.
 * Breakpoint `md` de Tailwind = 768px.
 */
function useMediaQuery(query: string): boolean {
    return React.useSyncExternalStore(
        (onChange) => {
            const media = window.matchMedia(query);
            media.addEventListener('change', onChange);
            return () => media.removeEventListener('change', onChange);
        },
        () => window.matchMedia(query).matches,
        () => false,
    );
}

/** Un icono puede llegar como componente lucide o como elemento ya pintado. */
function renderIcon(icon: PanelProps['icon']) {
    if (!icon) return null;
    if (typeof icon === 'function' || (typeof icon === 'object' && '$$typeof' in icon)) {
        const Icon = icon as LucideIcon;
        return <Icon aria-hidden className="mt-1 h-5 w-5 shrink-0 text-teal-300" />;
    }
    return icon;
}

/**
 * Panel de contenido: superficie unica (`--color-surface-1`), cabecera con
 * titulo/descripcion/acciones y plegado opcional.
 *
 * El plegado se resuelve con estado + clases, no con JS que mida el viewport:
 * un `<details>` puro sale cerrado en TODOS los tamaños y en escritorio
 * escondia el contenido sin pista de que se desplegaba. Con `"mobile"` el
 * contenido lleva `md:block`, asi que desde `md` siempre se ve aunque el
 * estado sea "plegado" y el HTML del servidor ya sale completo.
 */
export function Panel({
    title,
    icon,
    description,
    actions,
    collapsible = false,
    defaultOpen = false,
    density = 'default',
    titleAs = 'h2',
    className,
    children,
    ...props
}: PanelProps) {
    const t = useT();
    const hydrated = React.useSyncExternalStore(subscribeHydration, () => true, () => false);
    const [open, setOpen] = React.useState(defaultOpen);
    const contentId = React.useId();
    const mobileOnly = collapsible === 'mobile';
    const toggleable = collapsible === true || mobileOnly;
    const spacing = DENSITY_CLASSES[density];
    const isDesktop = useMediaQuery('(min-width: 768px)');

    // Con `collapsible="mobile"` el contenido SIEMPRE es visible desde `md`
    // (md:block): el estado expuesto a AT debe decirlo. Anunciar
    // aria-expanded={false} con el contenido a la vista contradice la pagina.
    const effectiveOpen = mobileOnly && isDesktop ? true : open;

    const bodyVisibility = !toggleable
        ? undefined
        : mobileOnly
          ? (effectiveOpen ? 'md:block' : 'hidden md:block')
          : (effectiveOpen ? undefined : 'hidden');

    return (
        <section
            className={cn('rounded-xl border border-gray-700/50 bg-surface-1', spacing.container, className)}
            {...props}
        >
            <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
                {renderIcon(icon)}
                <div className="min-w-0">
                    {React.createElement(titleAs, { className: 'text-base font-semibold text-gray-100' }, title)}
                    {description ? <p className="mt-1 text-sm text-gray-500">{description}</p> : null}
                </div>
                {actions ? (
                    <div className="ml-auto flex shrink-0 flex-wrap items-center justify-end gap-2">{actions}</div>
                ) : null}
                {toggleable ? (
                    <button
                        disabled={!hydrated}
                        aria-label={`${effectiveOpen ? t('ui.panel.collapse') : t('ui.panel.expand')} ${title}`}
                        aria-controls={contentId}
                        aria-expanded={effectiveOpen}
                        className={cn(
                            '-mr-2 -mt-1 flex size-11 shrink-0 items-center justify-center rounded-lg text-gray-500 transition hover:text-gray-200',
                            mobileOnly && 'md:hidden',
                        )}
                        onClick={() => setOpen((value) => !value)}
                        type="button"
                    >
                        <ChevronDown
                            className={cn('h-5 w-5 transition-transform', effectiveOpen ? 'rotate-180' : 'rotate-0')}
                        />
                        <span aria-hidden="true" className="sr-only">
                            {effectiveOpen ? t('ui.panel.collapse') : t('ui.panel.expand')} {title}
                        </span>
                    </button>
                ) : null}
            </div>
            <div className={cn(spacing.body, bodyVisibility)} id={contentId}>
                {children}
            </div>
        </section>
    );
}
