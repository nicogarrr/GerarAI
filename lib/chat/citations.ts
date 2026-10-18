/**
 * Citas trazables del chat: del backend (sources) al frontend con
 * localizador estable. Módulo puro (sin 'use server'): las server actions
 * no pueden exportar funciones síncronas.
 */

export interface ChatSource {
    type: string;
    id: number | string | null;
    title: string;
    document_id?: number | null;
    document_chunk_id?: number | null;
    page_number?: number | null;
    chunk_index?: number | null;
    source_type?: string | null;
    [key: string]: unknown;
}

/** Cita trazable: del backend (sources) al frontend con localizador estable. */
export interface ChatCitation {
    chunk_id: number | string | null;
    document: string;
    page: number | null;
    locator: string;
    source_type: string | null;
}

/** Deriva citations[{chunk_id,document,page,locator}] de los sources del backend. */
export function toChatCitations(
    sources: ChatSource[] | undefined | null,
): ChatCitation[] {
    if (!sources) return [];
    const citations: ChatCitation[] = [];
    for (const source of sources) {
        const kind = source.type;
        if (kind === 'document_chunk' || kind === 'rag_chunk' || kind === 'claim_evidence' || kind === 'knowledge_chunk') {
            const chunkId =
                kind === 'claim_evidence'
                    ? (source.document_chunk_id as number | null | undefined) ?? null
                    : source.id;
            const document =
                typeof source.title === 'string' && source.title
                    ? source.title
                    : `Documento ${String(source.document_id ?? '')}`.trim() || 'Documento';
            const page =
                typeof source.page_number === 'number' ? source.page_number : null;
            const locator =
                kind === 'claim_evidence'
                    ? `claim_evidence:${String(source.id)}`
                    : `${kind}:${String(source.id)}`;
            citations.push({
                chunk_id: chunkId,
                document,
                page,
                locator,
                source_type:
                    typeof source.source_type === 'string' ? source.source_type : null,
            });
        }
    }
    return citations;
}


export interface PortfolioChatCitation extends ChatCitation {
    url: string | null;
}

/** Keep backend sources visible without inventing links for internal records. */
export function toPortfolioChatCitations(sources: ChatSource[] | undefined | null): PortfolioChatCitation[] {
    return (sources ?? []).map((source) => {
        const existing = toChatCitations([source])[0];
        let url: string | null = null;
        if (typeof source.url === 'string' && (source.url === '/portfolio' || /^\/research\/[A-Za-z0-9.%_-]+(?:\?view=(?:financials|thesis|news))?$/.test(source.url))) {
            url = source.url;
        } else if (typeof source.url === 'string') {
            try {
                const parsed = new URL(source.url);
                if ((parsed.protocol === 'https:' || parsed.protocol === 'http:') && !parsed.username && !parsed.password) url = parsed.href;
            } catch { /* Missing or malformed URL: show provenance without a link. */ }
        }
        return {
            chunk_id: existing?.chunk_id ?? source.id,
            document: existing?.document ?? source.title,
            page: existing?.page ?? null,
            locator: existing?.locator ?? `${source.type}:${String(source.id)}`,
            source_type: existing?.source_type ?? source.type,
            url,
        };
    });
}

const CITATION_KIND_LABELS: Record<string, string> = {
    thesis_version: 'Tesis',
    thesis_section: 'Sección de tesis',
    financial_fact: 'Dato financiero',
    claim: 'Afirmación',
    claim_evidence: 'Evidencia',
    document_chunk: 'Documento',
    rag_chunk: 'Documento',
    memory_item: 'Nota guardada',
    portfolio: 'Cartera',
    position: 'Posición',
    knowledge_chunk: 'Biblioteca',
};

/**
 * Etiqueta legible del tipo de fuente. El localizador interno
 * (`financial_fact:123`) es un ID técnico y no se muestra al usuario.
 */
export function citationKindLabel(locator: string): string | null {
    const kind = locator.split(':', 1)[0] ?? '';
    return CITATION_KIND_LABELS[kind] ?? null;
}
