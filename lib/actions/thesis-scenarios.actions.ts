'use server';

import { researchRequest } from '@/lib/research/client';
import { getResearchThesisWorkspace } from '@/lib/actions/research.actions';

export type ScenarioKey = 'bear' | 'base' | 'bull';
export type ScenarioMetric = 'ingresos' | 'fcf' | 'bps';
export type ScenarioValue = { valor: number | null; etiqueta: string; motivo: string | null };
export type ScenarioYear = { ejercicio: number } & Record<ScenarioMetric, ScenarioValue>;
export type ThesisScenarios = {
  ticker: string;
  estado: 'persistido' | 'N/D';
  motivo: string | null;
  fuente: { tabla: string; version: number | null; modelo: string | null; fecha: string | null };
  escenarios: Record<ScenarioKey, { nombre: string; proyecciones: ScenarioYear[]; motivo: string | null }>;
  aviso_coherencia: string | null;
};

export async function getThesisScenarios(ticker: string): Promise<ThesisScenarios | null> {
  try {
    return await researchRequest<ThesisScenarios>(
      `/api/companies/${encodeURIComponent(ticker)}/thesis-scenarios`,
      { timeoutMs: 12_000 },
    );
  } catch {
    return null;
  }
}

/** Tesis y escenarios en paralelo; los escenarios degradan a null sin tumbar la tesis. */
export async function getThesisWithScenarios(ticker: string) {
  const scenariosRead = getThesisScenarios(ticker);
  const workspace = await getResearchThesisWorkspace(ticker);
  return { ...workspace, scenarios: await scenariosRead };
}
