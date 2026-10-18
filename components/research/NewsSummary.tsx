"use client";
import { useState } from 'react';
import type { ResearchNewsEvent } from '@/lib/actions/research.actions';

const nonLatin = /[\u0370-\u03ff\u0400-\u052f\u0600-\u06ff\u0900-\u097f\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]/;
const ENGLISH_MARK = /\b(the|with|says|shares|stocks|earnings|reports|raises|falls|after|amid|outlook|growth|investors|market|billion|million|revenue|warns|cuts|for|and|as|to|in)\b/i;

/** Resumen/cuerpo ingerido con traducción bajo demanda (Nico: traducir cada
 *  noticia desde la ficha y el feed). El original es inmutable: la traducción
 *  se pide al motor (cache por noticia, cadena gratuita) y se etiqueta; si
 *  no está disponible se queda el original sin meta-texto de fallo. */
export function NewsSummary({ event }: { event: ResearchNewsEvent }) {
  const original = (event.summary ?? '').trim();
  const [translated, setTranslated] = useState<string | null>(event.summary_translation?.text ?? null);
  const [showOriginal, setShowOriginal] = useState(false);
  const [busy, setBusy] = useState(false);
  if (!original) return null;
  const translatable = nonLatin.test(original) || ENGLISH_MARK.test(original);
  const onTranslate = () => {
    if (busy) return;
    setBusy(true);
    fetch(`/api/news/${event.id}/translation/summary`, { method: 'POST', signal: AbortSignal.timeout(17000) })
      .then(async res => {
        const data = res.ok ? await res.json() : null;
        if (data?.status === 'translated' && typeof data.text === 'string') setTranslated(data.text);
      })
      .catch(() => undefined)
      .finally(() => setBusy(false));
  };
  const showingTranslation = translated !== null && !showOriginal;
  return (
    <div className="mt-1">
      <p className="text-sm text-gray-400">{showingTranslation ? translated : original}</p>
      {translated !== null ? (
        <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-gray-500">
          <span>Traducción automática · español</span>
          <button className="min-h-11 text-teal-300 hover:text-teal-200 sm:min-h-0" type="button" onClick={() => setShowOriginal(v => !v)}>
            {showOriginal ? 'Ver traducción' : 'Ver original'}
          </button>
        </span>
      ) : translatable ? (
        <button className="mt-0.5 min-h-11 text-xs text-teal-300 hover:text-teal-200 sm:min-h-0" type="button" disabled={busy} onClick={onTranslate}>
          {busy ? 'Traduciendo…' : 'Traducir'}
        </button>
      ) : null}
    </div>
  );
}
