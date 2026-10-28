'use client';

import Link from 'next/link';

import { scrollToHashAnchor } from '@/lib/search/scroll-to-hash';

export const DECISION_JOURNAL_ANCHOR = 'diario-decisiones';

/**
 * Enlace «Diario de decisiones» de la ficha (?view=changes#diario-decisiones).
 *
 * Bug (suite E2E de flujos, 28-oct-2026): quitar `scroll={false}` no bastaba.
 * Con la página mínimamente desplazada (95 px en escritorio, y SIEMPRE en
 * móvil, donde hay que bajar hasta «Análisis avanzado»), el App Router
 * cambiaba la URL pero dejaba la vista donde estaba: el diario quedaba a
 * ~3.400 px. Solo funcionaba con la página exactamente arriba del todo. El
 * scroll al ancla es del llamador, igual que en la paleta (scroll-to-hash).
 */
export function DecisionJournalEntryLink({ ticker, className }: { ticker: string; className?: string }) {
  return <Link
    className={className}
    data-testid="decision-journal-entry"
    href={`/research/${encodeURIComponent(ticker)}?view=changes#${DECISION_JOURNAL_ANCHOR}`}
    onClick={(event) => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
      scrollToHashAnchor(DECISION_JOURNAL_ANCHOR);
    }}
  >Diario de decisiones <span aria-hidden="true">→</span></Link>;
}
