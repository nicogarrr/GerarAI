'use client';

import { useMemo, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { paginate } from '@/lib/research/change-events';
import { Pager } from './Pager';

export type ExpectationRow = {
  id: number;
  year: number;
  metric: string;
  expected: string;
  actual: string;
  status: string;
  /** Previsión de un ejercicio que aún no ha vencido y sin dato real: no es una comparación fallida. */
  pending: boolean;
};

const PAGE = 10;

function Rows({ rows }: { rows: ExpectationRow[] }) {
  return (
    <ul className="space-y-3">
      {rows.map((r) => (
        <li className="rounded-md border border-gray-800 p-3 text-sm" key={r.id}>
          <div className="flex items-start justify-between gap-2">
            <span className="font-medium text-gray-200">{r.year} · {r.metric}</span>
            <Badge variant="outline">{r.status}</Badge>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-gray-400">
            <span>Esperado <span className="text-gray-200">{r.expected}</span></span>
            <span className="text-right">Real <span className="text-gray-200">{r.actual}</span></span>
          </div>
        </li>
      ))}
    </ul>
  );
}

/**
 * Comparaciones esperado/real: las verificables (y las vencidas sin dato) se
 * paginan de 10 en 10; las previsiones de ejercicios futuros sin dato real
 * van plegadas en «Pendientes de vencimiento», agrupadas por año. No se
 * elimina ninguna: solo cambia dónde se ven.
 */
export function ExpectationsList({ rows }: { rows: ExpectationRow[] }) {
  const [page, setPage] = useState(1);
  const [pendingPage, setPendingPage] = useState(1);
  const main = useMemo(() => rows.filter((r) => !r.pending), [rows]);
  const pending = useMemo(() => rows.filter((r) => r.pending), [rows]);
  const view = paginate(main, page, PAGE);
  const pview = paginate(pending, pendingPage, PAGE);
  const years = useMemo(() => {
    const map = new Map<number, number>();
    for (const r of pending) map.set(r.year, (map.get(r.year) ?? 0) + 1);
    return [...map.entries()].sort((a, b) => a[0] - b[0]);
  }, [pending]);
  return (
    <div>
      {main.length ? (
        <>
          <Rows rows={view.items} />
          <Pager label="comparaciones" onPage={setPage} page={view.page} pages={view.pages} total={main.length} />
        </>
      ) : (
        <p className="text-sm text-gray-500">Ninguna comparación verificable todavía.</p>
      )}
      {pending.length ? (
        <details className="mt-4 rounded-md border border-gray-800 p-3" data-testid="expectations-pending">
          <summary className="min-h-11 cursor-pointer text-sm text-gray-300 sm:min-h-0">
            Pendientes de vencimiento ({pending.length})
            <span className="block text-xs text-gray-500">{years.map(([y, n]) => `${y}: ${n}`).join(' · ')}</span>
          </summary>
          <div className="mt-3">
            <Rows rows={pview.items} />
            <Pager label="previsiones" onPage={setPendingPage} page={pview.page} pages={pview.pages} total={pending.length} />
          </div>
        </details>
      ) : null}
    </div>
  );
}
