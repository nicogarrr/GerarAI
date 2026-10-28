import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * Densidad de la tabla. Las cabeceras escritas a mano usan `py-2 px-3` y las
 * que salen de este modulo usan `h-12 px-4`; convivir con las dos densidades a
 * la vez descuadraba la rejilla.
 *
 * `dense` se propaga con un atributo `data-dense` en el contenedor y la variante
 * `group-data-[dense]:` de Tailwind, NO con un contexto de React: este modulo lo
 * importan server components (app/(root)/watchlist/page.tsx, RecordViews...) y
 * en el runtime de RSC `React.createContext` no existe, lo que rompia
 * `next build` con "createContext is not a function".
 *
 * La densidad es una propiedad de la tabla ENTERA: no existe override por fila
 * o celda. Las utilidades directas (`p-4`) y las de grupo (`group-data:p-2`)
 * tienen la misma especificidad y colisionan por orden de la hoja generada, no
 * por la prop pasada, asi que un `dense={false}` local no ganaria al `dense`
 * del contenedor. Si una tabla necesita mezclar densidades, la celda concreta
 * lleva su propio `className` explicito en el punto de uso.
 */
type DensityProps = { dense?: boolean }

type TableProps = React.HTMLAttributes<HTMLTableElement> &
  DensityProps & {
    /**
     * Nombre accesible de la region con scroll horizontal. Con teclado no hay
     * barra de scroll, asi que sin `tabIndex` el contenido ancho queda
     * inalcanzable (WCAG 2.1.1). Solo debe pasarse cuando la tabla puede
     * desbordar de verdad: un `tabIndex` en un contenedor quieto crea un stop de
     * tabulacion inutil.
     */
    regionLabel?: string
  }

const Table = React.forwardRef<HTMLTableElement, TableProps>(
  ({ className, dense = false, regionLabel, ...props }, ref) => (
    // `overflow-x-auto` y no `overflow-auto`: con `auto` en ambos ejes el
    // contenedor se lleva el scroll vertical de la pagina al hacer scroll sobre
    // la tabla, y `min-w-0` evita que la tabla ensanche un contenedor flex.
    <div
      data-slot="table-region"
      data-dense={dense ? "" : undefined}
      className="group/table scroll-affordance-x relative w-full min-w-0 overflow-x-auto"
      {...(regionLabel
        ? { role: "region", "aria-label": regionLabel, tabIndex: 0 }
        : null)}
    >
      <table
        ref={ref}
        className={cn("w-full caption-bottom text-sm", className)}
        {...props}
      />
    </div>
  )
)
Table.displayName = "Table"

const TableHeader = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <thead ref={ref} className={cn("[&_tr]:border-b", className)} {...props} />
))
TableHeader.displayName = "TableHeader"

const TableBody = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tbody
    ref={ref}
    className={cn("[&_tr:last-child]:border-0", className)}
    {...props}
  />
))
TableBody.displayName = "TableBody"

const TableFooter = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tfoot
    ref={ref}
    className={cn(
      "border-t bg-muted/50 font-medium [&>tr]:last:border-b-0",
      className
    )}
    {...props}
  />
))
TableFooter.displayName = "TableFooter"

const TableRow = React.forwardRef<
  HTMLTableRowElement,
  React.HTMLAttributes<HTMLTableRowElement>
>(({ className, ...props }, ref) => (
  <tr
    ref={ref}
    className={cn(
      "border-b border-gray-700/50 transition-all duration-150 hover:bg-gray-700/30 data-[state=selected]:bg-gray-700/50",
      "group-data-[dense]/table:[&>th]:px-3 group-data-[dense]/table:[&>th]:py-2 group-data-[dense]/table:[&>th]:h-auto group-data-[dense]/table:[&>td]:p-2",
      className
    )}
    {...props}
  />
))
TableRow.displayName = "TableRow"

const TableHead = React.forwardRef<
  HTMLTableCellElement,
  React.ThHTMLAttributes<HTMLTableCellElement> & {
    /** `col` por defecto: sin esto ningun lector de pantalla anuncia las
     *  cabeceras. Se puede pasar `row` si el `th` rotula la fila. */
    scope?: React.ThHTMLAttributes<HTMLTableCellElement>["scope"]
  }
>(({ className, scope = "col", ...props }, ref) => (
  <th
    ref={ref}
    scope={scope}
    className={cn(
      "h-12 px-4 text-left align-middle font-medium text-muted-foreground [&:has([role=checkbox])]:pr-0",
      // La densidad se hereda del contenedor por CSS (ver docblock del modulo).
      "group-data-[dense]/table:h-auto group-data-[dense]/table:px-3 group-data-[dense]/table:py-2",
      className
    )}
    {...props}
  />
))
TableHead.displayName = "TableHead"

const TableCell = React.forwardRef<
  HTMLTableCellElement,
  React.TdHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => (
  <td
    ref={ref}
    className={cn(
      "p-4 align-middle [&:has([role=checkbox])]:pr-0",
      "group-data-[dense]/table:p-2",
      className
    )}
    {...props}
  />
))
TableCell.displayName = "TableCell"

/** Se apila en el DOM (`<caption>` es el primero de `<table>`): da nombre a la
 *  tabla en el modo lectura y es el destino de `aria-describedby`. Pasar
 *  `className="sr-only"` cuando el titulo visible ya esta en el `<h2>`. */
const TableCaption = React.forwardRef<
  HTMLTableCaptionElement,
  React.HTMLAttributes<HTMLTableCaptionElement>
>(({ className, ...props }, ref) => (
  <caption
    ref={ref}
    className={cn("mt-4 text-sm text-muted-foreground", className)}
    {...props}
  />
))
TableCaption.displayName = "TableCaption"

export {
  Table,
  TableHeader,
  TableBody,
  TableFooter,
  TableHead,
  TableRow,
  TableCell,
  TableCaption,
}
