/**
 * F394: el motor valora por acción ORDINARIA; el precio cotizado de un ADR es
 * por ADR. El backend entrega los escenarios ya convertidos (listed_share_values)
 * y cada tesis persiste SU propia base al generarse. El cliente nunca multiplica:
 * solo elige qué valores mostrar y cómo rotularlos.
 */
export type ScenarioKey = 'bear' | 'base' | 'bull' | 'expected';
export type ScenarioValues = Record<ScenarioKey, number | string | null | undefined>;

export type ValuationBasis = {
  value_per_share_basis?: string | null;
  adr_ratio?: number | null;
  // null por clave: escenario N/D (valor por acción <= 0), nunca cifra negativa.
  listed_share_values?: Partial<Record<ScenarioKey, number | null>> | null;
} | null | undefined;

export type ScenarioDisplay = {
  values: ScenarioValues;
  /** Sufijo para las etiquetas de escenario; vacío si la base no necesita aviso. */
  label: string;
};

function pickListed(
  listed: Partial<Record<ScenarioKey, number | null>> | null | undefined,
): ScenarioValues | null {
  if (!listed || typeof listed !== 'object') return null;
  const out = {} as ScenarioValues;
  for (const key of ['bear', 'base', 'bull', 'expected'] as const) {
    const value = listed[key];
    out[key] = typeof value === 'number' && Number.isFinite(value) ? value : null;
  }
  return out;
}

function adrLabel(ratio: number | null | undefined, locale: 'es' | 'en' = 'es'): string {
  const per = locale === 'en' ? 'per ADR' : 'por ADR';
  return typeof ratio === 'number' && Number.isFinite(ratio) && ratio > 0
    ? ` (${per}, ×${ratio})`
    : ` (${per})`;
}

const UNVERIFIED_BASIS: Record<'es' | 'en', string> = {
  es: ' (base por acción no verificada)',
  en: ' (per-share basis not verified)',
};

/** Hay ratio ADR distinto de 1 pero sin valores listados: la base no se puede afirmar. */
function unlistedRatioLabel(basis: ValuationBasis, locale: 'es' | 'en' = 'es'): string {
  const ratio = basis?.adr_ratio;
  return typeof ratio === 'number' && Number.isFinite(ratio) && ratio > 0 && ratio !== 1
    ? UNVERIFIED_BASIS[locale]
    : '';
}

/**
 * Tesis persistida. Sin evidencia de base (tesis anterior) no se escala nada:
 * se etiqueta como base no verificada (no se afirma ninguna).
 */
export function thesisScenarioDisplay(
  original: ScenarioValues,
  basis: ValuationBasis,
  locale: 'es' | 'en' = 'es',
): ScenarioDisplay {
  if (!basis) return { values: original, label: UNVERIFIED_BASIS[locale] };
  const listed = pickListed(basis.listed_share_values);
  if (listed) return { values: listed, label: adrLabel(basis.adr_ratio, locale) };
  return { values: original, label: unlistedRatioLabel(basis, locale) };
}

/** Valoración en vivo: usa los campos de su propia respuesta. */
export function valuationScenarioDisplay(
  original: ScenarioValues,
  basis: ValuationBasis,
  locale: 'es' | 'en' = 'es',
): ScenarioDisplay {
  const listed = pickListed(basis?.listed_share_values);
  if (listed) return { values: listed, label: adrLabel(basis?.adr_ratio, locale) };
  return { values: original, label: unlistedRatioLabel(basis, locale) };
}
