import { researchRequest } from '@/lib/research/client';

/**
 * Tesis v2 de nivel comité (data-engine app/services/expert_team/thesis_v2.py):
 * todas las cifras y las tablas llegan ya calculadas y formateadas por el
 * código; el texto lo redactan los agentes con marcadores sustituidos en el
 * servidor. Aquí solo tipos, la lectura y helpers puros.
 */
export type ThesisV2Table = { title: string; head: string[]; rows: string[][] };
export type ThesisV2Section = { key: string; title: string; text: string; tables: ThesisV2Table[] };
export type ThesisV2 = {
  status: string | null;
  ticker: string;
  company: string;
  version: string;
  as_of: string | null;
  fingerprint: string | null;
  probability_choice: string | null;
  probability_reason: string | null;
  sections: ThesisV2Section[];
  headline: {
    price: string | null;
    tir5: string | null;
    tir10: string | null;
    base_tir10: string | null;
    multiple: string | null;
    peers_median: string | null;
    cost_of_equity: string | null;
  };
  warnings: string[];
  sources: string[];
  llm_calls: number | null;
  stale?: boolean;
};

export async function getThesisV2(ticker: string): Promise<ThesisV2 | null> {
  try {
    const out = await researchRequest<{ status: string; thesis: ThesisV2 | null }>(
      `/api/companies/${encodeURIComponent(ticker)}/thesis-v2`,
      { timeoutMs: 20000 },
    );
    return out?.thesis && Array.isArray(out.thesis.sections) && out.thesis.sections.length ? out.thesis : null;
  } catch {
    return null;
  }
}

/** Párrafos del texto de una sección (líneas en blanco), sin vacíos. */
export function thesisParagraphs(text: string | null | undefined): string[] {
  return (text ?? '')
    .split(/\n\s*\n/)
    .map((p) => p.replace(/\s+/g, ' ').trim())
    .filter(Boolean);
}

/** Una tabla se pinta si tiene cabecera y al menos una fila. */
export function hasRows(table: ThesisV2Table | null | undefined): table is ThesisV2Table {
  return !!table && Array.isArray(table.head) && table.head.length > 0 && Array.isArray(table.rows) && table.rows.length > 0;
}
