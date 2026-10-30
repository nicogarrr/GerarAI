'use client';
import { useT } from '@/lib/i18n/client';

import * as React from 'react';

import { Button } from '@/components/ui/button';
import {
  DEFAULT_PAGE_SIZE,
  clampPage,
  pageLabel,
  paginateItems,
} from '@/lib/ux/pagination';
import { cn } from '@/lib/utils';

export type PaginationProps = {
  page: number;
  pages: number;
  onPageChange: (page: number) => void;
  /** Nombre accesible del bloque (p. ej. «Historial de versiones»). */
  label: string;
  className?: string;
  /** Hay más páginas en el servidor aún sin cargar: «Siguiente» sigue activo y el total se muestra como «N+». */
  hasMore?: boolean;
  /** Deshabilita los botones mientras se carga una página. */
  busy?: boolean;
};

/**
 * Controles Anterior/Siguiente con la página actual expuesta a lectores de
 * pantalla. Vive en cliente porque la página de research no puede convertirse
 * entera en cliente solo para paginar dos listados.
 */
export function Pagination({ page, pages, onPageChange, label, className, hasMore = false, busy = false }: PaginationProps) {
  const t = useT();
  const current = clampPage(page, pages);
  if (pages <= 1 && !hasMore) return null;

  return (
    <nav
      aria-label={t('ui.pagination.aria', { label })}
      className={cn('flex flex-wrap items-center justify-between gap-3 text-sm', className)}
    >
      <Button
        aria-label={t('ui.pagination.prevAria', { label })}
        disabled={busy || current <= 1}
        onClick={() => onPageChange(current - 1)}
        size="sm"
        type="button"
        variant="outline"
      >
        Anterior
      </Button>
      <span aria-current="page" className="text-xs text-gray-500">
        {busy ? t('common.states.loading') : hasMore ? `${pageLabel(current, pages)}+` : pageLabel(current, pages)}
      </span>
      <Button
        aria-label={t('ui.pagination.nextAria', { label })}
        disabled={busy || (current >= pages && !hasMore)}
        onClick={() => onPageChange(current + 1)}
        size="sm"
        type="button"
        variant="outline"
      >
        Siguiente
      </Button>
    </nav>
  );
}

export type PagedListItem = {
  key: string;
  node: React.ReactNode;
};

export type PagedListProps = {
  items: PagedListItem[];
  /** Nombre accesible del listado y de sus controles. */
  label: string;
  pageSize?: number;
  className?: string;
  listClassName?: string;
};

/**
 * Lista paginada de 10 en 10. Recibe elementos ya renderizados por el servidor
 * (así la ficha no se convierte en cliente) y conserva la página al plegar o
 * desplegar el contenedor: el estado vive aquí, no en el `<details>`.
 */
export function PagedList({
  items,
  label,
  pageSize = DEFAULT_PAGE_SIZE,
  className,
  listClassName,
}: PagedListProps) {
  const [requestedPage, setRequestedPage] = React.useState(1);
  const slice = paginateItems(items, requestedPage, pageSize);

  return (
    <div className={className}>
      <div className={cn(listClassName ?? 'space-y-3')}>
        {slice.items.map((item) => (
          <React.Fragment key={item.key}>{item.node}</React.Fragment>
        ))}
      </div>
      <Pagination
        className="mt-3"
        label={label}
        onPageChange={setRequestedPage}
        page={slice.page}
        pages={slice.pages}
      />
    </div>
  );
}
