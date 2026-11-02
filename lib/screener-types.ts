/** Contrato del motor de screeners del backend (criterios y filas de
 *  resultado). Lo comparten la acción del motor (screener.actions) y la de
 *  pantallas guardadas (research-tools.actions), que antes copiaban los
 *  tipos campo a campo. */

export type ScreenCriterion = {
  left: string;
  operator: '>' | '>=' | '<' | '<=' | '==' | '!=';
  right: string;
};

export type EngineScreenRow = {
  company_id: number;
  ticker: string;
  name: string;
  matched: boolean;
  rank_value: string | null;
  coverage_percent: number;
  confidence: string;
  latest_data_at: string | null;
  missing_fields: string[];
};

/** Fila de una pantalla guardada: la del motor más el detalle por criterio. */
export type ScreenResultRow = EngineScreenRow & {
  criteria: Array<ScreenCriterion & {
    left_value?: string;
    right_value?: string;
    passed: boolean;
    missing_fields?: string[];
  }>;
};

export type ScreenResult = {
  criteria: ScreenCriterion[];
  ranking_formula: string | null;
  ranking_direction: string;
  company_count: number;
  match_count: number;
  metrics_without_data?: string[];
  new_match_company_ids?: number[];
  results: ScreenResultRow[];
};

export type EngineScreenResult = {
  criteria: ScreenCriterion[];
  ranking_formula: string | null;
  ranking_direction: string;
  company_count: number;
  match_count: number;
  new_match_company_ids?: number[];
  results: EngineScreenRow[];
};
