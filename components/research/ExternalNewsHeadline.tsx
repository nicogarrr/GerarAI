'use client';
import { useEffect, useRef, useState } from 'react';
import { isTranslatable } from '@/lib/news-language';
import { useLocale, useT } from '@/lib/i18n/client';

// Cola con concurrencia 2, como NewsHeadline: antes era serie de 1 y una fila
// lenta (hasta 12 s de timeout) frenaba las traducciones de las demás filas.
const queue: Array<() => void> = [];
let running = 0;
function drain() { while (running < 2 && queue.length) { running++; queue.shift()!(); } }
const pending = new Map<string, Promise<string | null>>();
function translate(headline: string): Promise<string | null> {
  const existing = pending.get(headline);
  if (existing) return existing;
  const job = new Promise<string | null>(resolve => {
    queue.push(() => {
      fetch('/api/news/translate-headline', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({headline}), signal:AbortSignal.timeout(12000)})
        .then(async response => {
          const data = response.ok ? await response.json() : null;
          resolve(data?.status === 'translated' && typeof data.text === 'string' ? data.text : null);
        })
        .catch(() => resolve(null))
        .finally(() => { running--; drain(); });
    });
    drain();
  });
  if (pending.size >= 512) pending.delete(pending.keys().next().value!);
  pending.set(headline, job);
  return job;
}

/** Display only. The original source remains accessible, never overwritten. */
export function ExternalNewsHeadline({headline, url, className = ''}: {headline: string; url?: string | null; className?: string}) {
  const t = useT();
  // Con Ajustes → Idioma en inglés no se traduce al español (antes un titular
  // en inglés se pasaba a español): se pinta el original sin aviso.
  const english = useLocale() === 'en';
  // La traducción se guarda con el titular al que pertenece: si el prop cambia,
  // no se pinta el texto de la fila anterior mientras llega la nueva.
  const [translation, setTranslation] = useState<{
    headline: string;
    text: string | null;
    state: 'loading' | 'translated' | 'original';
  } | null>(null);
  const current = translation?.headline === headline ? translation : null;
  const text = current?.text ?? null;
  const translationState = current?.state ?? 'idle';
  const ref = useRef<HTMLDivElement>(null);
  const canTranslate = !english && headline.length <= 500 && headline.length >= 3 && isTranslatable(headline);
  useEffect(() => {
    // Regla espejo de needs_translation (lib/news-language.ts), la misma que
    // NewsHeadline: un titular ya español no dispara petición (el backend
    // también corta con not_needed, pero así se ahorra el POST por fila).
    if (!ref.current || !canTranslate) return;
    let active = true;
    const observer = new IntersectionObserver(entries => {
      if (!entries.some(entry => entry.isIntersecting)) return;
      observer.disconnect();
      setTranslation({ headline, text: null, state: 'loading' });
      translate(headline).then(value => {
        if (!active) return;
        setTranslation({ headline, text: value, state: value ? 'translated' : 'original' });
      });
    });
    observer.observe(ref.current);
    return () => {active = false;observer.disconnect();};
  }, [headline, canTranslate]);
  // Si el titular es extranjero y no hay traducción utilizable, se dice: el
  // texto visible es el original, no una versión en español.
  const showOriginalLabel = !english && isTranslatable(headline) && (translationState === 'original' || !canTranslate);
  return <div ref={ref}>
    <div className={className}>{url ? <a href={url} target="_blank" rel="noopener noreferrer" className="hover:text-teal-200">{text ?? headline}</a> : (text ?? headline)}</div>
    {showOriginalLabel && <p className="mt-1 text-xs text-amber-300">{t('research.translate.originalHeadline')}</p>}
    {text && <details className="mt-1 text-xs text-gray-400"><summary className="relative z-10 cursor-pointer py-1">{t('research.translate.autoViewOriginal')}</summary><p className="relative z-10 mt-1 break-words">{url ? <a href={url} target="_blank" rel="noopener noreferrer" className="hover:underline">{headline}</a> : headline}</p></details>}
  </div>;
}
