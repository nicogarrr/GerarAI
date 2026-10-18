/** Contrato v1 congelado del asistente de investigación. Sin writeback. */
export type AssistantMode = 'explore' | 'guide';
export type AssistantSectionKey = 'facts' | 'calculations' | 'hypotheses' | 'inferences' | 'contradictions' | 'insufficient_data' | 'conclusion';
export type AssistantCitationKind = 'news_event' | 'financial_fact' | 'document_chunk' | 'claim_evidence' | 'market_observation' | 'thesis_record';
export type AssistantRequest = {
  mode: AssistantMode;
  question: string;
  ticker?: string;
  review_id?: number;
};
export type AssistantResponse = {
  mode: AssistantMode;
  status: 'answered' | 'insufficient_data';
  answer: string;
  sections: Array<{ key: AssistantSectionKey; body: string; citation_ids: string[] }>;
  citations: Array<{
    id: string;
    kind: AssistantCitationKind;
    source: string;
    url: string | null;
    as_of: string | null;
    excerpt: string | null;
  }>;
  missing_data: string[];
  suggested_next_steps: string[];
  review_id: number | null;
  writeback: false;
};
export type GuideContext = {
  ticker: string;
  review_id: number | null;
  open_reviews: Array<{ id: number; status: string; summary: string }>;
  latest_news: Array<{ id: number; title: string; source: string; source_url: string | null; date: string | null; date_source: string | null }>;
  missing_data: string[];
};

/** URL de fuente no confiable: nunca convertir esquemas ejecutables ni credenciales en enlaces. */
export function safeAssistantSourceUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return (url.protocol === 'http:' || url.protocol === 'https:') &&
      !!url.hostname && !url.username && !url.password ? url.href : null;
  } catch {
    return null;
  }
}
