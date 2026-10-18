'use client';
import { useEffect, useRef, useState } from 'react';

const pending = new Map<string, Promise<string | null>>();
let tail: Promise<unknown> = Promise.resolve();
function translate(headline: string) {
  const existing = pending.get(headline);
  if (existing) return existing;
  const job = tail.then(async () => {
    try {
      const response = await fetch('/api/news/translate-headline', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({headline}), signal:AbortSignal.timeout(12000)});
      const data = response.ok ? await response.json() : null;
      return data?.status === 'translated' && typeof data.text === 'string' ? data.text : null;
    } catch { return null; }
  });
  tail = job;
  if (pending.size >= 512) pending.delete(pending.keys().next().value!);
  pending.set(headline, job);
  return job;
}

/** Display only. The original source remains accessible, never overwritten. */
export function ExternalNewsHeadline({headline, url, className = ''}: {headline: string; url?: string | null; className?: string}) {
  const [text, setText] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || headline.length > 500 || headline.length < 3) return;
    let active = true;
    const observer = new IntersectionObserver(entries => {
      if (!entries.some(entry => entry.isIntersecting)) return;
      observer.disconnect();
      translate(headline).then(value => {if (active) setText(value);});
    });
    observer.observe(ref.current);
    return () => {active = false;observer.disconnect();};
  }, [headline]);
  return <div ref={ref}>
    <div className={className}>{url ? <a href={url} target="_blank" rel="noopener noreferrer" className="hover:text-teal-200">{text ?? headline}</a> : (text ?? headline)}</div>
    {text && <details className="mt-1 text-xs text-gray-400"><summary className="relative z-10 cursor-pointer py-1">Traducción automática · ver original</summary><p className="relative z-10 mt-1 break-words">{url ? <a href={url} target="_blank" rel="noopener noreferrer" className="hover:underline">{headline}</a> : headline}</p></details>}
  </div>;
}
