import * as React from 'react'

import { cn } from '@/lib/utils'

/**
 * Semantica del dato: neutro, positivo, aviso o negativo. Se aplica SOLO al
 * value; el label mantiene siempre la tinta secundaria para que la cifra sea
 * lo unico que cambia de color.
 */
export type StatTone = 'default' | 'good' | 'warn' | 'bad'

/** `md` para cifras de cabecera; `sm` para rejillas densas (terminal, intelligence). */
export type StatSize = 'sm' | 'md'

const TONE_CLASSES: Record<StatTone, string> = {
  default: 'text-gray-100',
  good: 'text-good',
  warn: 'text-warn',
  bad: 'text-bad',
}

const VALUE_SIZE_CLASSES: Record<StatSize, string> = {
  md: 'text-2xl font-semibold',
  // En móvil las rejillas `sm` van a 2 columnas (~125 px útiles por tarjeta):
  // a text-lg una cifra como «100.000,00 €» no cabía y `break-words` la partía
  // dejando el «€» solo en otra línea. text-base hasta `sm:` + padding p-3.
  sm: 'text-base font-semibold sm:text-lg',
}

const PADDING_CLASSES: Record<StatSize, string> = {
  md: 'p-4',
  sm: 'p-3 sm:p-4',
}

export interface StatProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Nombre del dato. Se pinta en versalitas sobre tinta secundaria. */
  label: string
  value: React.ReactNode
  tone?: StatTone
  size?: StatSize
  /** Contexto opcional debajo de la cifra (periodo, unidad, fuente). */
  hint?: React.ReactNode
}

/**
 * Cifra con etiqueta para las rejillas de KPIs. Antes cada pagina traia su
 * propia copia (tres `Stat` locales y cuatro variantes escritas a mano) y cada
 * una elegia un hex distinto de fondo. Aqui vive una sola vez: la superficie
 * es `--color-surface-1` y el color del dato sale de los tokens semanticos.
 *
 * El contenedor es un `div` neutro y acepta `className` para las variantes de
 * rejilla (por ejemplo `col-span-2`); no lleva `role`/`aria` porque el patron
 * completo (nombre accesible del dato) se resuelve en otro sitio.
 */
function Stat({ label, value, tone = 'default', size = 'md', hint, className, ...props }: StatProps) {
  return (
    <div
      className={cn(
        'min-w-0 rounded-xl border border-gray-700/50 bg-surface-1',
        PADDING_CLASSES[size],
        className
      )}
      {...props}
    >
      <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">
        {label}
      </div>
      <div className={cn('mt-2 break-words tabular-nums', VALUE_SIZE_CLASSES[size], TONE_CLASSES[tone])}>
        {value}
      </div>
      {hint ? <div className="mt-1 text-xs text-gray-500">{hint}</div> : null}
    </div>
  )
}

export { Stat }
