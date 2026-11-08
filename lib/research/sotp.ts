import { cache } from 'react';

import { parseLocalizedNumberDetailed } from '@/lib/format';
import { researchRequest } from '@/lib/research/client';

/**
 * Desglose por partes (SOTP) editable del usuario: GET/PUT/DELETE
 * /api/valuation/{ticker}/sotp. Son supuestos del usuario, no el valor justo
 * de GerarAI; el backend añade siempre la tasa base medida de las empresas que
 * queman caja. Importes en millones de la divisa del modelo.
 */

export type SotpPart = {
  name: string;
  kind: 'operating' | 'asset';
  group?: string | null;
  note?: string | null;
  probability?: number;
  revenue?: number | null;
  ebitda?: number | null;
  ebitda_margin?: number | null;
  multiple?: number | null;
  value?: number | null;
  discounted?: boolean;
};

export type SotpScenario = {
  key: string;
  label: string;
  note?: string | null;
  revenue_factor?: number | null;
  multiple_factor?: number | null;
  delay_years?: number | null;
  discount_rate?: number | null;
  shares_total?: number | null;
  stated_value_per_share?: number | null;
};

export type SotpModel = {
  /** Ausente = la de la empresa (la pone el backend al guardar). */
  currency?: string | null;
  base_year: number;
  valuation_year: number;
  discount_years?: number | null;
  discount_rate: number;
  shares_current: number;
  dilution: { label: string; shares: number }[];
  parts: SotpPart[];
  scenarios: SotpScenario[];
  author?: string | null;
  source?: string | null;
  stated_value_per_share?: number | null;
};

export type SotpRow = {
  name: string;
  kind: 'operating' | 'asset';
  group: string | null;
  revenue: number | null;
  ebitda: number | null;
  ebitda_margin: number | null;
  multiple: number | null;
  probability: number;
  value_at_maturity: number;
  value_at_maturity_weighted: number;
  discount_factor: number;
  present_value: number;
  value_per_share: number;
};

export type SotpResult = {
  rows: SotpRow[];
  total_value_at_maturity: number;
  total_present_value: number;
  total_revenue: number;
  total_ebitda: number;
  weighted_multiple: number | null;
  shares_diluted: number;
  discount_rate: number;
  discount_years: number;
  discount_factor: number;
  value_per_share: number;
  price: number | null;
  vs_price: number | null;
  stated_value_per_share: number | null;
  stated_gap: number | null;
  price_covered_by: { name: string; value_per_share: number; cumulative_per_share: number; covers_price: boolean }[];
  scenarios: (SotpScenario & { computed: boolean; value_per_share: number | null; vs_price: number | null; stated_vs_price: number | null; stated_gap: number | null })[];
  sensitivity: { key: string; label: string; value_per_share: number; vs_base: number | null; vs_price: number | null }[];
};

export type SotpBaseRate = {
  applies: boolean | null;
  fiscal_year: number | null;
  cases: number;
  median_return_24m: number;
  fell_over_half_24m_share: number;
  doubled_24m_share: number;
  beat_spy_24m_share: number;
  message_es: string | null;
  message_en: string | null;
};

export type SotpResponse = {
  ticker: string;
  available: boolean;
  origin?: 'saved' | 'example';
  label: string;
  validated: false;
  model?: SotpModel;
  result?: SotpResult;
  price?: number | null;
  price_currency?: string | null;
  price_as_of?: string | null;
  base_rate: SotpBaseRate;
  saved?: { row_id: number; saved_at: string | null; versions: number } | null;
};

export const getSotp = cache(async (ticker: string): Promise<SotpResponse | null> => {
  try {
    return await researchRequest<SotpResponse>(`/api/valuation/${encodeURIComponent(ticker.toUpperCase())}/sotp`);
  } catch {
    return null;
  }
});

/** Filas vacías extra del formulario para añadir partes, diluciones y escenarios. */
export const SOTP_EXTRA_PARTS = 3;
export const SOTP_EXTRA_DILUTION = 1;
export const SOTP_EXTRA_SCENARIOS = 1;

export type SotpFormResult = { ok: true; model: SotpModel } | { ok: false; field: string; message: string };

type Getter = (key: string) => string;
/** Traductor (t de getT/useT): el parser no lleva textos propios. */
type Tr = (key: string, vars?: Record<string, string | number>) => string;

const K = 'research.sotp.';
/** Claves literales (el guard de i18n busca cada clave escrita entera). */
const ERR = {
  required: 'research.sotp.err.required',
  ambiguous: 'research.sotp.err.ambiguous',
  notNumber: 'research.sotp.err.notNumber',
  missingMultiple: 'research.sotp.err.missingMultiple',
  missingEbitda: 'research.sotp.err.missingEbitda',
  missingValue: 'research.sotp.err.missingValue',
  noParts: 'research.sotp.err.noParts',
  dilutionDefault: 'research.sotp.dilutionDefault',
} as const;

function num(get: Getter, tr: Tr, key: string, label: string, opts: { required?: boolean; percent?: boolean } = {}): number | null | { error: string } {
  const raw = (get(key) ?? '').trim();
  if (!raw) return opts.required ? { error: tr(ERR.required, { label }) } : null;
  const parsed = parseLocalizedNumberDetailed(raw);
  if (!parsed.ok) return { error: tr(parsed.error === 'ambiguous' ? ERR.ambiguous : ERR.notNumber, { label }) };
  return opts.percent ? parsed.value / 100 : parsed.value;
}

function isError(value: unknown): value is { error: string } {
  return typeof value === 'object' && value !== null && 'error' in value;
}

/**
 * Formulario → modelo. Pura (recibe un getter y el traductor) para testearla sin
 * FormData. Una fila sin nombre se ignora; tasas, márgenes y probabilidades van en %.
 */
export function sotpModelFromForm(get: Getter, counts: { parts: number; dilution: number; scenarios: number }, tr: Tr): SotpFormResult {
  const fail = (field: string, message: string): SotpFormResult => ({ ok: false, field, message });
  const globals: Record<string, number | null> = {};
  for (const [key, labelKey, percent] of [
    ['base_year', 'baseYear', false],
    ['valuation_year', 'valuationYear', false],
    ['discount_rate', 'rate', true],
    ['shares_current', 'sharesCurrent', false],
  ] as const) {
    const value = num(get, tr, key, tr(K + labelKey), { required: true, percent });
    if (isError(value)) return fail(key, value.error);
    globals[key] = value;
  }
  const parts: SotpPart[] = [];
  for (let i = 0; i < counts.parts; i++) {
    const name = (get(`part_name_${i}`) ?? '').trim();
    if (!name) continue;
    const kind = get(`part_kind_${i}`) === 'asset' ? 'asset' : 'operating';
    const fields: Record<string, number | null> = {};
    for (const [key, labelKey, percent] of [
      ['revenue', 'revenue', false], ['ebitda', 'ebitda', false], ['ebitda_margin', 'margin', true],
      ['multiple', 'multiple', false], ['value', 'assetValue', false], ['probability', 'probabilityField', true],
    ] as const) {
      const value = num(get, tr, `part_${key}_${i}`, `${name} · ${tr(K + labelKey)}`, { percent });
      if (isError(value)) return fail(`part_${key}_${i}`, value.error);
      fields[key] = value;
    }
    const part: SotpPart = { name, kind, group: (get(`part_group_${i}`) ?? '').trim() || null, note: (get(`part_note_${i}`) ?? '').trim() || null };
    if (fields.probability !== null) part.probability = fields.probability;
    if (kind === 'operating') {
      if (fields.multiple === null) return fail(`part_multiple_${i}`, tr(ERR.missingMultiple, { name }));
      if (fields.ebitda === null && fields.ebitda_margin === null) return fail(`part_ebitda_${i}`, tr(ERR.missingEbitda, { name }));
      Object.assign(part, { revenue: fields.revenue, ebitda: fields.ebitda, ebitda_margin: fields.ebitda_margin, multiple: fields.multiple });
    } else {
      if (fields.value === null) return fail(`part_value_${i}`, tr(ERR.missingValue, { name }));
      Object.assign(part, { value: fields.value, discounted: get(`part_discounted_${i}`) !== 'no' });
    }
    parts.push(part);
  }
  if (!parts.length) return fail('part_name_0', tr(ERR.noParts));
  const dilution: SotpModel['dilution'] = [];
  for (let i = 0; i < counts.dilution; i++) {
    const label = (get(`dil_label_${i}`) ?? '').trim() || tr(ERR.dilutionDefault, { n: i + 1 });
    const shares = num(get, tr, `dil_shares_${i}`, label);
    if (isError(shares)) return fail(`dil_shares_${i}`, shares.error);
    if (shares === null) continue;
    dilution.push({ label, shares });
  }
  const scenarios: SotpScenario[] = [];
  for (let i = 0; i < counts.scenarios; i++) {
    const label = (get(`sc_label_${i}`) ?? '').trim();
    if (!label) continue;
    const scenario: SotpScenario = { key: (get(`sc_key_${i}`) ?? '').trim() || `s${i + 1}`, label, note: (get(`sc_note_${i}`) ?? '').trim() || null };
    for (const [key, labelKey, percent] of [
      ['revenue_factor', 'revenueFactor', false], ['multiple_factor', 'multipleFactor', false], ['delay_years', 'delay', false],
      ['discount_rate', 'rate', true], ['shares_total', 'sharesTotal', false], ['stated_value_per_share', 'statedScenario', false],
    ] as const) {
      const value = num(get, tr, `sc_${key}_${i}`, `${label} · ${tr(K + labelKey)}`, { percent });
      if (isError(value)) return fail(`sc_${key}_${i}`, value.error);
      if (value !== null) scenario[key] = value;
    }
    scenarios.push(scenario);
  }
  const stated = num(get, tr, 'stated_value_per_share', tr(`${K}statedTotal`));
  if (isError(stated)) return fail('stated_value_per_share', stated.error);
  return {
    ok: true,
    model: {
      currency: (get('currency') ?? '').trim().toUpperCase() || null,
      base_year: globals.base_year as number,
      valuation_year: globals.valuation_year as number,
      discount_rate: globals.discount_rate as number,
      shares_current: globals.shares_current as number,
      dilution,
      parts,
      scenarios,
      author: (get('author') ?? '').trim() || null,
      source: (get('source') ?? '').trim() || null,
      stated_value_per_share: stated,
    },
  };
}
