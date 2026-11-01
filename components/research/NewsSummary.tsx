"use client";
import { useState } from 'react';
import type { ResearchNewsEvent } from '@/lib/actions/research.actions';
import { newsSummaryToShow } from '@/lib/news-summary';
import { isTranslatable } from '@/lib/news-language';
import { useT } from '@/lib/i18n/client';


/** Motivo estable que devuelve el motor (campo `reason` de la API) → texto
 *  honesto para la persona. Medido en prod 19-oct-2026: un fallo devolvía el
 *  botón a «Traducir» sin decir nada. Sin motivo conocido, mensaje genérico. */
const REASON_KEYS = {
  cooldown: 'research.translate.reason.cooldown',
  busy: 'research.translate.reason.busy',
  budget: 'research.translate.reason.budget',
  quota: 'research.translate.reason.quota',
  bad_output: 'research.translate.reason.badOutput',
  provider_rate_limited: 'research.translate.reason.providerRateLimited',
  provider_timeout: 'research.translate.reason.providerTimeout',
  provider: 'research.translate.reason.provider',
  changed: 'research.translate.reason.changed',
} as const;

/** Resumen/cuerpo ingerido con traducción bajo demanda (Nico: traducir cada
 *  noticia desde la ficha y el feed). El original es inmutable: la traducción
 *  se pide al motor (cache por noticia, cadena gratuita) y se etiqueta; si
 *  no está disponible se queda el original y se muestra el motivo. */
export function NewsSummary({ event }: { event: ResearchNewsEvent }) {
  const t = useT();
  // El helper comparte la regla del resto de superficies: un resumen que solo
  // repite el titular no se pinta (la ingesta SEC sintética guarda
  // summary === title y pintarlo duplicaba el prefijo «TICKER »).
  // Titulares generados por GerarAI (headline_from_source === false, p. ej. el
  // cluster 13F «N movimientos institucionales») no llevan resumen: el cuerpo
  // crudo del agregador es boilerplate y ensuciaba la fila. El helper recibe
  // la fuente para recortar restos de proveedor («News TradingView»).
  const original = event.headline_from_source === false
    ? ''
    : newsSummaryToShow(event.title ?? '', event.summary, event.source) ?? '';
  const [translated, setTranslated] = useState<string | null>(event.summary_translation?.text ?? null);
  const [showOriginal, setShowOriginal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  if (!original) return null;
  const translatable = isTranslatable(original);
  const onTranslate = () => {
    if (busy) return;
    setBusy(true);
    setFailure(null);
    fetch(`/api/news/${event.id}/translation/summary`, { method: 'POST', signal: AbortSignal.timeout(17000) })
      .then(async res => {
        const data = res.ok ? await res.json() : null;
        if (data?.status === 'translated' && typeof data.text === 'string') {
          setTranslated(data.text);
        } else {
          setFailure(typeof data?.reason === 'string' ? data.reason : 'unknown');
        }
      })
      .catch(() => setFailure('unknown'))
      .finally(() => setBusy(false));
  };
  const showingTranslation = translated !== null && !showOriginal;
  return (
    <div className="mt-1">
      <p className="text-sm text-gray-400">{showingTranslation ? translated : original}</p>
      {translated !== null ? (
        <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-gray-500">
          <span>{t('research.translate.autoLabel')}</span>
          <button className="min-h-11 text-teal-300 hover:text-teal-200 sm:min-h-0" type="button" onClick={() => setShowOriginal(v => !v)}>
            {showOriginal ? t('research.translate.viewTranslation') : t('research.translate.viewOriginal')}
          </button>
        </span>
      ) : translatable ? (
        <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs">
          <button className="min-h-11 text-teal-300 hover:text-teal-200 sm:min-h-0" type="button" disabled={busy} onClick={onTranslate}>
            {busy ? t('research.translate.translating') : t('research.translate.translate')}
          </button>
          {failure ? (
            <span className="text-gray-500" role="status">
              {Object.hasOwn(REASON_KEYS, failure) ? t(REASON_KEYS[failure as keyof typeof REASON_KEYS]) : t('research.translate.genericFailure')}
            </span>
          ) : null}
        </span>
      ) : null}
    </div>
  );
}
