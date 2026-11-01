'use client';

import { useId, useRef, useState } from 'react';
import dynamic from 'next/dynamic';
import { ChevronLeft, ChevronRight } from 'lucide-react';

// react-markdown + remark-gfm (~47 KB gzip con micromark/hast) solo pintan el
// cuerpo del memorando: cargarlos en el bundle inicial de /research/[ticker]
// los pagaban también las vistas que nunca abren el memo. Import diferido con
// esqueleto; la cabecera del paginador (anterior/siguiente) responde ya.
const ThesisMarkdown = dynamic(() => import('@/components/research/ThesisMarkdown'), {
  loading: () => (
    <div className="space-y-2" aria-hidden="true">
      <div className="h-4 w-3/4 animate-pulse rounded bg-slate-800/60" />
      <div className="h-4 w-full animate-pulse rounded bg-slate-800/60" />
      <div className="h-4 w-5/6 animate-pulse rounded bg-slate-800/60" />
    </div>
  ),
});
import { Button } from '@/components/ui/button';
import { useT } from '@/lib/i18n/client';
import type { MemoPage } from '@/lib/research/memo-pages';

/**
 * Memorando completo paginado: una sección por pantalla, anterior/siguiente y
 * selector fijo arriba. Sin scroll infinito. Al cambiar de página solo se
 * recoloca el inicio del memorando si ya quedó fuera de vista.
 */
export default function ThesisMarkdownPager({ pages }: { pages: MemoPage[] }) {
  const t = useT();
  const [index, setIndex] = useState(0);
  const top = useRef<HTMLDivElement>(null);
  const selectId = useId();
  if (pages.length === 0) return null;
  const safeIndex = Math.min(index, pages.length - 1);
  const page = pages[safeIndex];

  function go(next: number) {
    setIndex(next);
    const el = top.current;
    if (el && el.getBoundingClientRect().top < 0) el.scrollIntoView({ block: 'start' });
  }

  return (
    <div ref={top} className="scroll-mt-16">
      <div className="sticky top-0 z-10 -mx-1 flex items-center gap-2 border-b border-gray-800 bg-gray-950/95 px-1 py-2 backdrop-blur">
        <Button aria-label={t('research.memoPager.previous')} disabled={safeIndex === 0} onClick={() => go(safeIndex - 1)} size="icon" type="button" variant="outline">
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <label className="sr-only" htmlFor={selectId}>{t('research.memoPager.select')}</label>
        <select
          className="h-11 min-w-0 flex-1 rounded-md border border-gray-700 bg-gray-900 px-2 text-base text-gray-100 sm:h-9 sm:text-sm"
          id={selectId}
          onChange={(event) => go(Number(event.target.value))}
          value={safeIndex}
        >
          {pages.map((entry, i) => (
            <option key={entry.id} value={i}>{i + 1}. {entry.title}</option>
          ))}
        </select>
        <span className="shrink-0 text-xs tabular-nums text-gray-500">{safeIndex + 1}/{pages.length}</span>
        <Button aria-label={t('research.memoPager.next')} disabled={safeIndex === pages.length - 1} onClick={() => go(safeIndex + 1)} size="icon" type="button" variant="outline">
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
      <div className="mt-3">
        <ThesisMarkdown content={page.body} />
      </div>
      <div className="mt-3 flex justify-between">
        <Button disabled={safeIndex === 0} onClick={() => go(safeIndex - 1)} type="button" variant="outline">Anterior</Button>
        <Button disabled={safeIndex === pages.length - 1} onClick={() => go(safeIndex + 1)} type="button" variant="outline">Siguiente</Button>
      </div>
    </div>
  );
}
