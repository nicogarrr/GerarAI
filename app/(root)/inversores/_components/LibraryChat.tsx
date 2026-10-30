'use client';

import { BrainGlassesIcon } from '@/components/brain/BrainGlassesIcon';
import { BRAIN_LIBRARY_CONTEXT_ID, openBrain, type KnowledgeBrainContext } from '@/lib/brain/open-brain';

type LibraryChatProps = {
  scope?: KnowledgeBrainContext['scope'];
  authors?: string[];
  documentId?: number;
  documentTitle?: string;
  /** Texto del botón compacto; por defecto «Preguntar a la biblioteca». */
  label?: string;
  className?: string;
};

/**
 * Acceso al Cerebro desde las páginas de doctrina (Biblioteca, cartas, lector).
 *
 * Antes el Cerebro se incrustaba aquí como un panel de 780 px en mitad de la
 * página (entre las pestañas y el contenido de /knowledge): Nico lo quería
 * como en el resto de la app, pequeño abajo a la derecha y plegado. Ahora la
 * página solo declara su contexto en un marcador oculto (que el Cerebro
 * global del layout lee para preguntar a esta biblioteca al abrirse) y ofrece
 * un botón compacto que abre ese mismo Cerebro flotante. No hay un segundo
 * asistente: es el mismo panel, con la misma conversación.
 */
export function LibraryChat({ scope = 'letters', authors = [], documentId, documentTitle, label = 'Preguntar a la biblioteca', className = '' }: LibraryChatProps) {
  const knowledge: KnowledgeBrainContext = {
    scope,
    authors,
    ...(documentId ? { documentId } : {}),
    ...(documentTitle ? { documentTitle } : {}),
  };
  return (
    <>
      <span
        hidden
        id={BRAIN_LIBRARY_CONTEXT_ID}
        data-scope={scope}
        data-authors={JSON.stringify(authors)}
        data-document-id={documentId}
        data-document-title={documentTitle}
      />
      <button
        type="button"
        onClick={() => openBrain({ knowledge })}
        className={`inline-flex h-11 w-full items-center justify-center gap-2 rounded-md border border-indigo-500/40 bg-indigo-950/30 px-4 text-sm font-medium text-indigo-200 transition hover:border-indigo-400/60 hover:text-white sm:w-auto ${className}`}
      >
        <BrainGlassesIcon aria-hidden="true" className="h-5 w-5 shrink-0 object-contain" />
        {label}
      </button>
    </>
  );
}
