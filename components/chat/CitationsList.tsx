'use client';

import { FileText } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { formatNumber } from '@/lib/format';
import { citationKindLabel, toChatCitations, type ChatCitation } from '@/lib/chat/citations';
import { useT } from '@/lib/i18n/client';

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
    const t = useT();
    const derived: ChatCitation[] =
        citations.length > 0 || !sources ? citations : toChatCitations(sources);

    if (derived.length === 0) return null;

    return (
        <div className="mt-4 border-t border-gray-800 pt-3">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                {t('chat.citations.title', { n: formatNumber(derived.length, { maximumFractionDigits: 0 }) })}
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
