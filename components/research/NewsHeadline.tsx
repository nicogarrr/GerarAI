"use client";
import { useEffect, useRef, useState } from 'react';
import type { ResearchNewsEvent } from '@/lib/actions/research.actions';
import { newsDisplayTitle } from '@/lib/news-display';
import { isTranslatable } from '@/lib/news-language';
import { RelatedTickersStrip } from '@/components/research/RelatedTickersStrip';

const queue: Array<() => void> = [];
let running = 0;
function drain() { while (running < 2 && queue.length) { running++; queue.shift()!(); } }
function translate(id: number): Promise<string | null> {
  return new Promise(resolve => {
    queue.push(() => {
      fetch(`/api/news/${id}/translation`, {method:'POST', signal:AbortSignal.timeout(14000)})
        .then(async res => { const data = res.ok ? await res.json() : null; resolve(data?.status === 'translated' && typeof data.text === 'string' ? data.text : null); })
        .catch(() => resolve(null)).finally(() => {running--;drain();});
    });
    drain();
  });
}

export function NewsHeadline({ event }: { event: ResearchNewsEvent }) {
  const original = event.original_headline ?? event.title;
  const [translated, setTranslated] = useState<string | null>(event.headline_translation?.text ?? null);
  const ref = useRef<HTMLDivElement>(null);
  const needsTranslation = event.headline_from_source !== false && isTranslatable(original);
  useEffect(() => {
    if (!needsTranslation || translated || !ref.current) return;
    let active = true;
    const observer = new IntersectionObserver(entries => {
      if (!entries.some(entry => entry.isIntersecting)) return;
      observer.disconnect();
      translate(event.id).then(text => {if (active && text) {setTranslated(text);}});
    });
    observer.observe(ref.current);
    return () => {active=false;observer.disconnect();};
  }, [event.id, needsTranslation, translated]);
  const title = translated ?? newsDisplayTitle(event.title, event.ticker, event.headline_from_source, event.original_headline);
  return <div ref={ref} className="break-words">
    {event.url ? <a className="inline-flex min-h-11 items-center hover:text-teal-200" href={event.url} rel="noreferrer" target="_blank">{title}</a> : title}
    {translated ? <><span className="mt-1 block text-xs text-gray-500">Traducción automática · español</span><details className="mt-1 text-xs text-gray-400"><summary className="min-h-11 cursor-pointer py-3">Ver original</summary><p className="mt-1 break-words">{original}</p></details></> : null}
    <RelatedTickersStrip items={event.related_tickers} />
  </div>;
}
