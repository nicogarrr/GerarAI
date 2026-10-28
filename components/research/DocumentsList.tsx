'use client';

import { useMemo, useState } from 'react';
import { FileText } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { paginate } from '@/lib/research/change-events';
import { Pager } from './Pager';

export type DocumentRow = { id: number | string; title: string; url: string | null; tier: string; type: string; published: string };

const PAGE = 10;

/** Documentos de la ficha: búsqueda por título/tipo y 10 por página. */
export function DocumentsList({ documents }: { documents: DocumentRow[] }) {
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? documents.filter((d) => `${d.title} ${d.type} ${d.tier}`.toLowerCase().includes(q)) : documents;
  }, [documents, query]);
  const view = paginate(filtered, page, PAGE);
  return (
    <div>
      {documents.length > PAGE ? (
        <input
          aria-label="Buscar documentos"
          className="mb-3 h-11 w-full rounded-md border border-gray-700 bg-gray-900 px-3 text-sm text-gray-200 placeholder:text-gray-500 sm:h-10"
          onChange={(e) => { setQuery(e.target.value); setPage(1); }}
          placeholder="Buscar por título o tipo"
          type="search"
          value={query}
        />
      ) : null}
      {view.items.length ? (
        <div className="space-y-3">
          {view.items.map((d) => (
            <div className="rounded-lg border border-gray-800 p-4" key={d.id}>
              <div className="flex flex-wrap items-center gap-2">
                <FileText className="h-4 w-4 text-teal-300" />
                {d.url ? <a className="font-medium text-gray-200 underline decoration-gray-700 underline-offset-4 transition hover:text-teal-200" href={d.url} rel="noopener noreferrer" target="_blank">{d.title}</a> : <span className="font-medium text-gray-200">{d.title}</span>}
                <Badge variant="outline">{d.tier}</Badge>
              </div>
              <p className="mt-2 text-xs text-gray-500">{d.type} · {d.published}</p>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-gray-500">Ningún documento coincide con la búsqueda.</p>
      )}
      <Pager label="documentos" onPage={setPage} page={view.page} pages={view.pages} total={filtered.length} />
    </div>
  );
}
