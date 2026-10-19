'use server';

import { researchRequest } from '@/lib/research/client';

/**
 * Cuellos de botella: senales deterministas (2+ fuentes independientes) y
 * candidatos INFERIDOS por el modelo a partir de esas senales.
 *
 * Sin catch a proposito, como en getMarketThemes: si el backend no responde,
 * la pagina muestra el estado "desconectado" en vez de una lista vacia que
 * parezca un dato. Ambos GET son solo lectura sobre lo persistido: ni ingieren
 * ni llaman a ningun modelo.
 */
export interface BottleneckSignalView {
  theme: string;
  evidence_ids: string[];
  evidence?: DiscoveryEvidenceView[];
  first_seen: string | null;
  last_seen: string | null;
  n_sources: number;
  status: 'N/D' | 'detectado';
}

export interface BottlenecksState {
  signals: BottleneckSignalView[];
  /** Umbral vigente de 'detectado' en el backend: la etiqueta N/D lo muestra. */
  min_sources: number;
  method: string;
  limitation: string;
}

export interface DiscoveryEvidenceView {
  id: string;
  title: string | null;
  url: string | null;
  status: 'verificada' | 'N/D';
}

export interface DiscoveryView {
  id: number;
  theme: string;
  ticker: string;
  label: 'INFERIDO';
  reasoning: string;
  evidence: DiscoveryEvidenceView[];
  model: string;
  created_at: string;
}

export interface DiscoveriesState {
  items: DiscoveryView[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  note: string;
}

export async function getBottlenecks(): Promise<BottlenecksState> {
  const payload = await researchRequest<BottlenecksState>('/api/bottlenecks');
  if (!payload || !Array.isArray(payload.signals)) {
    throw new Error('Respuesta de cuellos de botella no válida.');
  }
  return payload;
}

export async function getBottleneckDiscoveries(offset: number, limit = 20): Promise<DiscoveriesState> {
  const safeOffset = Number.isFinite(offset) && offset > 0 ? Math.floor(offset) : 0;
  const safeLimit = Math.min(Math.max(Math.floor(limit), 1), 100);
  const payload = await researchRequest<DiscoveriesState>(
    `/api/bottlenecks/discoveries?limit=${safeLimit}&offset=${safeOffset}`,
  );
  if (!payload || !Array.isArray(payload.items)) {
    throw new Error('Respuesta de candidatos de descubrimiento no válida.');
  }
  return payload;
}

/** Explicit user request: the worker enforces free-model and daily quota gates. */
export async function runBottleneckDiscovery() {
  await researchRequest('/api/bottlenecks/discoveries/run', {method: 'POST'});
  return {message: 'Barrido inferido en cola. No garantiza candidatos: vuelve a cargar el listado cuando termine.'};
}
