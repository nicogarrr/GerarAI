import { FileText } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { formatNumber } from '@/lib/format';
import { citationKindLabel, type ChatCitation } from '@/lib/chat/citations';

interface CitationsListProps {
    citations: ChatCitation[];
    /** Sources crudos del backend (para compat con la vista de research). */
    sources?: Array<{
        type: string;
        id: number | string | null;
        title: string;
        [key: string]: unknown;
    }>;
}

/**
 * Renderiza citations[{chunk_id,document,page,locator}] del chat.
 * Acepta citas ya derivadas o los sources crudos del backend (los deriva
 * con la misma regla que lib/chat/citations.ts:toChatCitations).
 */
export default function CitationsList({ citations, sources }: CitationsListProps) {
    const derived: ChatCitation[] =
        citations.length > 0 || !sources
            ? citations
            : sources
                  .filter(
                      (s) =>
                          s.type === 'document_chunk' ||
                          s.type === 'rag_chunk' ||
                          s.type === 'claim_evidence',
                  )
                  .map((s) => ({
                      chunk_id:
                          s.type === 'claim_evidence'
                              ? ((s.document_chunk_id as number | null | undefined) ?? null)
                              : s.id,
                      document: typeof s.title === 'string' && s.title ? s.title : 'Documento',
                      page: typeof s.page_number === 'number' ? s.page_number : null,
                      locator:
                          s.type === 'claim_evidence'
                              ? `claim_evidence:${String(s.id)}`
                              : `${s.type}:${String(s.id)}`,
                      source_type:
                          typeof s.source_type === 'string' ? s.source_type : null,
                  }));

    if (derived.length === 0) return null;

    return (
        <div className="mt-4 border-t border-gray-800 pt-3">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                Citas y evidencia ({formatNumber(derived.length, { maximumFractionDigits: 0 })})
            </h4>
            <ul className="mt-2 space-y-2">
                {derived.map((citation) => (
                    <li
                        key={citation.locator}
                        className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-gray-400"
                    >
                        <FileText className="h-3.5 w-3.5 shrink-0 text-teal-400" />
                        <span className="min-w-0 flex-1 truncate text-gray-300" title={citation.document}>
                            {citation.document}
                        </span>
                        {citation.page !== null ? (
                            <Badge variant="outline">p. {citation.page}</Badge>
                        ) : null}
                        <code className="rounded bg-black/40 px-1.5 py-0.5 font-mono text-[11px] text-gray-500">
                            {citationKindLabel(citation.locator)}
                        </code>
                    </li>
                ))}
            </ul>
        </div>
    );
}
