'use client';

import { openBrain } from '@/lib/brain/open-brain';

/** Contextual entry only. Questions and answers live in the single Cerebro. */
export function LibraryChat({ scope = 'letters', authors = [] }: { scope?: 'letters' | 'library'; authors?: string[] }) {
  return <section aria-label="Preguntar a la biblioteca" className="flex min-w-0 flex-col gap-3 rounded-xl border border-gray-800 p-4">
    <h2 className="text-xl font-semibold">{scope === 'letters' ? 'Cartas en el Cerebro' : 'Biblioteca en el Cerebro'}</h2>
    <p className="text-xs text-amber-300">Doctrina, no datos actuales de empresas. Síntesis del modelo con citas; el original manda.</p>
    <button type="button" onClick={() => openBrain({ knowledge: { scope, authors } })} className="min-h-[44px] rounded-lg bg-teal-300 px-4 py-2 text-sm font-medium text-gray-950">Preguntar al Cerebro</button>
  </section>;
}
