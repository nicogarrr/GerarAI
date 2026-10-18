import type { ResearchThesis } from '@/lib/actions/research.actions';

/** Un input del modelo con su procedencia etiquetada por el backend. */
export type ProvenanceItem = NonNullable<ResearchThesis['inputs_provenance']>[number];

/** Fail-closed: solo es OFICIAL lo que llega marcado OFICIAL con TODAS sus
 *  fuentes oficiales, https y con fecha. Todo lo demás (payload legacy, sin
 *  origen, etiquetas derivado/supuesto/estimación) se muestra como INFERIDO. */
export function isVerifiedOficial(item: ProvenanceItem): boolean {
  const fuentes = item.fuentes ?? [];
  return (
    item.origen === 'OFICIAL' &&
    fuentes.length > 0 &&
    fuentes.every((f) => f.oficial && !!f.fecha && !!f.url && /^https:\/\//.test(f.url))
  );
}

/** Enlaces https de la fuente: documentos citados del dato o URLs de la inferencia. */
export function provenanceUrls(item: ProvenanceItem): string[] {
  const cited = (item.fuentes ?? []).map((f) => f.url);
  return Array.from(new Set([...cited, ...(item.urls_inferencia ?? [])].filter(
    (url): url is string => typeof url === 'string' && /^https:\/\//.test(url),
  )));
}
