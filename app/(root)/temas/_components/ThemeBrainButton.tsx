'use client';

import { BrainGlassesIcon } from '@/components/brain/BrainGlassesIcon';
import { useT } from '@/lib/i18n/client';

type ThemeBrainButtonProps = {
  /** Pregunta de análisis ya escrita (con los datos actuales del tema). */
  question: string;
};

/**
 * Cohesión Temas ↔ Cerebro: abre el panel con la pregunta de análisis del
 * tema ya escrita; el usuario solo la envía (puede editarla antes).
 */
export function ThemeBrainButton({ question }: ThemeBrainButtonProps) {
  const t = useT();
  return (
    <button
      type="button"
      onClick={() =>
        window.dispatchEvent(new CustomEvent('gerarai:open-brain', { detail: { question } }))
      }
      className="mt-3 inline-flex min-h-11 items-center gap-2 rounded-lg border border-gray-800 px-3 text-xs font-semibold text-teal-300 transition hover:border-teal-400/40 hover:text-teal-200"
    >
      <BrainGlassesIcon className="h-4 w-4" />
      {t('themes.brain.button')}
    </button>
  );
}
