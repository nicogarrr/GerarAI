import * as React from 'react'
import Link from 'next/link'
import type { LucideIcon } from 'lucide-react'

import { cn } from '@/lib/utils'

export interface EmptyStateProps {
  /** Icono decorativo (lucide). Se oculta a lectores de pantalla. */
  icon?: LucideIcon
  title: string
  description?: React.ReactNode
  /** Primer paso: boton, enlace o formulario. */
  action?: React.ReactNode
  /**
   * Elemento del titulo. Por defecto `p` porque casi siempre vive dentro de un
   * `Panel` (que ya aporta su `h2`) y anadir otro encabezado duplicaria el
   * nivel. Las paginas cuyo estado vacio ES el encabezado de la pagina pasan
   * `titleAs="h1"`.
   */
  titleAs?: 'h1' | 'h2' | 'h3' | 'p'
  className?: string
}

/**
 * Estado vacio unico del producto: borde punteado, icono, que falta y que
 * hacer. Sustituye a los once `border border-dashed` sueltos que cada pagina
 * escribia a su manera (y a los componentes locales `Empty`/`EmptyLink`).
 */
function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  titleAs = 'p',
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        'rounded-lg border border-dashed border-gray-700/50 p-8 text-center',
        className
      )}
    >
      {Icon ? <Icon aria-hidden className="mx-auto h-8 w-8 text-gray-500" /> : null}
      {React.createElement(
        titleAs,
        { className: cn('break-words text-base font-semibold text-gray-100', Icon && 'mt-3') },
        title
      )}
      {description ? (
        <p className="mx-auto mt-1 max-w-xl break-words text-sm text-gray-500">{description}</p>
      ) : null}
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  )
}

/**
 * Enlace-CTA de los estados vacios ("primer paso"). Es solo el enlace: el marco
 * punteado y los textos los pone `EmptyState`.
 */
function EmptyLink({
  href,
  children,
  className,
}: {
  href: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <Link
      className={cn(
        'inline-flex min-h-[44px] sm:min-h-0 items-center gap-2 rounded-md border border-teal-800 px-3 py-2 text-xs font-medium text-teal-300 transition hover:border-teal-600 hover:text-teal-200',
        className
      )}
      href={href}
    >
      {children}
    </Link>
  )
}

export { EmptyState, EmptyLink }
