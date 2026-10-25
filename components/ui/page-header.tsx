import * as React from 'react'

import { cn } from '@/lib/utils'

export interface PageHeaderProps {
    /** Antetitulo en versalitas (familia de la pagina). */
    kicker?: string
    title: string
    description?: React.ReactNode
    /** Boton de vuelta, arriba a la izquierda (normalmente `Button asChild`). */
    back?: React.ReactNode
    /** Acciones alineadas al borde inferior derecho en escritorio. */
    actions?: React.ReactNode
    /** Contenido adicional bajo el titulo (p. ej. pestañas de la pagina). */
    children?: React.ReactNode
    className?: string
}

/**
 * Cabecera de pagina: `border-b` + antetitulo + `h1` + subtitulo. El patron
 * estaba copiado en siete paginas de research, cada una con su combinacion de
 * `gap`, `lg:`/`md:` y ancho de subtitulo. El `h1` conserva `text-3xl font-bold
 * text-gray-100` porque es el ancla de los `getByRole("heading", { level: 1 })`
 * de los e2e.
 */
export function PageHeader({ kicker, title, description, back, actions, children, className }: PageHeaderProps) {
    return (
        <header className={cn('border-b border-gray-800 pb-5', className)}>
            <div className={cn('flex flex-col gap-4', actions && 'lg:flex-row lg:items-end lg:justify-between')}>
                <div className="min-w-0">
                    {back ? <div className="mb-4">{back}</div> : null}
                    {kicker ? <p className="text-sm font-semibold uppercase text-teal-300">{kicker}</p> : null}
                    <h1 className="mt-1 text-3xl font-bold text-gray-100">{title}</h1>
                    {description ? <p className="mt-2 max-w-3xl text-sm text-gray-400">{description}</p> : null}
                    {children ? <div className="mt-4">{children}</div> : null}
                </div>
                {actions ? <div className="flex flex-wrap items-center gap-3">{actions}</div> : null}
            </div>
        </header>
    )
}
