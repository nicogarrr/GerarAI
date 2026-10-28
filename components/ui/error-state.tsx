import * as React from 'react'
import { AlertTriangle } from 'lucide-react'

import { cn } from '@/lib/utils'

export interface ErrorStateProps {
  title: string
  /** Qué ha fallado y qué no significa (un fallo no es «sin datos»). */
  description?: React.ReactNode
  /** Reintento o salida (enlace o botón). */
  action?: React.ReactNode
  /** Igual que `EmptyState`: `h1` cuando el error ES el contenido de la página. */
  titleAs?: 'h1' | 'h2' | 'h3' | 'p'
  className?: string
}

/**
 * Estado de error de carga. Hermano de `EmptyState` con otra forma a propósito:
 * borde continuo ámbar e icono de aviso, para que un fallo del backend nunca se
 * lea como un estado vacío («todavía no hay…»). El color no es la única pista:
 * el icono y el texto dicen que es un error.
 */
function ErrorState({ title, description, action, titleAs = 'p', className }: ErrorStateProps) {
  return (
    <div
      role="alert"
      className={cn('rounded-lg border border-amber-800/60 bg-amber-950/20 p-6 text-left', className)}
    >
      <div className="flex items-start gap-3">
        <AlertTriangle aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-warn" />
        <div className="min-w-0">
          {React.createElement(
            titleAs,
            { className: 'text-base font-semibold text-gray-100' },
            title
          )}
          {description ? <p className="mt-1 max-w-xl text-sm text-gray-400">{description}</p> : null}
          {action ? <div className="mt-4 flex flex-wrap gap-2">{action}</div> : null}
        </div>
      </div>
    </div>
  )
}

export { ErrorState }
