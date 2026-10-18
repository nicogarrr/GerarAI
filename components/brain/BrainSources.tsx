import { citationKindLabelFor, type PortfolioChatCitation } from '@/lib/chat/citations';

export function BrainSources({ citations }: { citations?: PortfolioChatCitation[] }) {
    if (!citations?.length) return null;
    return (
        <section aria-label="Fuentes de esta respuesta" className="mt-3 border-t border-slate-600 pt-2 text-xs not-prose">
            <h4 className="font-semibold text-slate-200">Fuentes</h4>
            <ul className="mt-1 space-y-2">
                {citations.map((citation, index) => (
                    <li key={`${citation.locator}-${index}`} className="min-w-0 break-words">
                        {citation.url ? (
                            <a href={citation.url} target="_blank" rel="noopener noreferrer" className="text-indigo-300 underline underline-offset-2 hover:text-indigo-200">
                                {citation.document}
                            </a>
                        ) : <span className="text-slate-200">{citation.document}</span>}
                        {citation.page !== null && <span className="text-slate-400"> · Página {citation.page}</span>}
                        {citationKindLabelFor(citation) && (
                            <span className="mt-0.5 block text-slate-400">{citationKindLabelFor(citation)}</span>
                        )}
                    </li>
                ))}
            </ul>
        </section>
    );
}
