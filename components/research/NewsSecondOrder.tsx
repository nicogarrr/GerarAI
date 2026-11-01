'use client';

import Link from 'next/link';
import { useState, type ReactNode } from 'react';
import { useT } from '@/lib/i18n/client';

type Candidate = {
  ticker: string;
  company_name: string | null;
  direction: 'beneficiada' | 'perjudicada' | 'incierta';
  exposure: { field: string; value: string };
  causal_chain: { cause: string; effect: string }[];
};
type SecondOrder = {
  status: 'hipótesis_no_verificadas' | 'sin_datos';
  mode: 'determinista' | 'llm';
  candidates: Candidate[];
};
type Load = { state: 'idle' } | { state: 'loading' } | { state: 'error' } | { state: 'ready'; data: SecondOrder };

const GROUPS = [
  { key: 'beneficiada', labelKey: 'research.flow.second.benefited' },
  { key: 'perjudicada', labelKey: 'research.flow.second.harmed' },
  { key: 'incierta', labelKey: 'research.flow.second.uncertain' },
] as const;
const PER_GROUP = 8;

/**
 * Único desplegable por fila de noticia: el contexto de la fuente (children,
 * server-rendered) y los efectos de segundo orden (carga perezosa al abrir).
 */
export function NewsSecondOrder({ eventId, summary, subjectTicker, children }: { eventId: number; summary: string; subjectTicker?: string | null; children?: ReactNode }) {
  const t = useT();
  const [load, setLoad] = useState<Load>({ state: 'idle' });

  async function fetchOnce() {
    if (load.state !== 'idle' && load.state !== 'error') return;
    setLoad({ state: 'loading' });
    try {
      const res = await fetch(`/api/news/${eventId}/second-order`, { signal: AbortSignal.timeout(58_000) });
      const data = res.ok ? ((await res.json()) as SecondOrder) : null;
      setLoad(data && Array.isArray(data.candidates) ? { state: 'ready', data } : { state: 'error' });
    } catch {
      setLoad({ state: 'error' });
    }
  }

  return (
    <details className="mt-2 text-xs text-gray-400" onToggle={(event) => { if ((event.currentTarget as HTMLDetailsElement).open) void fetchOnce(); }}>
      <summary className="min-h-11 cursor-pointer py-2 text-teal-300">{summary}</summary>
      {children}
      {load.state === 'loading' ? <p className="mt-1" role="status">{t('research.flow.second.loading')}</p> : null}
      {load.state === 'error' ? <p className="mt-1">{t('research.flow.second.error')}</p> : null}
      {load.state === 'ready' && load.data.status === 'sin_datos' ? (
        <p className="mt-1">
          {subjectTicker
            ? t('research.flow.second.noneWithSubject', { ticker: subjectTicker })
            : t('research.flow.second.none')}
        </p>
      ) : null}
      {load.state === 'ready' && load.data.status !== 'sin_datos' ? (
        <div className="mt-1 space-y-3 rounded-md border border-gray-800 p-2">
          <p className="font-medium text-gray-300">{t('research.flow.second.hypotheses')} · {load.data.mode === 'llm' ? t('research.flow.second.modeModel') : t('research.flow.second.modeRules')}</p>
          {GROUPS.map((group) => {
            const items = load.data.candidates.filter((item) => item.direction === group.key);
            if (!items.length) return null;
            return (
              <div key={group.key}>
                <h4 className="font-semibold text-gray-200">{t(group.labelKey)} ({items.length})</h4>
                <ul className="mt-1 space-y-1">
                  {items.slice(0, PER_GROUP).map((item) => (
                    <li className="break-words" key={`${group.key}-${item.ticker}`}>
                      <Link className="inline-flex min-h-11 min-w-11 items-center font-semibold text-teal-300 hover:text-teal-200" href={`/research/${item.ticker}`}>{item.ticker}</Link>
                      {item.company_name ? ` · ${item.company_name}` : ''}
                      <span className="text-gray-500"> · {item.exposure.value}</span>
                      {item.causal_chain[0] ? <span className="block text-gray-500">{item.causal_chain[0].cause} → {item.causal_chain[0].effect}</span> : null}
                    </li>
                  ))}
                </ul>
                {items.length > PER_GROUP ? <p className="mt-1 text-gray-500">{t('research.flow.second.more', { count: items.length - PER_GROUP })}</p> : null}
              </div>
            );
          })}
        </div>
      ) : null}
    </details>
  );
}
