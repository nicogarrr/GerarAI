/**
 * Cruce explícito Temas de mercado <-> Cuellos de botella.
 *
 * Mapeo curado a mano entre las 17 cestas de /temas y los 6 temas de escasez
 * de /cuellos. Es deliberadamente conservador: solo se enlaza cuando el
 * solape es directo y explicable (p. ej. la cesta "Materiales críticos" son
 * mineras de cobre/litio/tierras raras/uranio -> "Minerales"). "Transporte"
 * no tiene cesta equivalente y no se enlaza. Sin inferencia por LLM.
 */
export const THEME_TO_BOTTLENECK: Record<string, string> = {
  semiconductores: 'Semiconductores',
  'centros-de-datos': 'Centros de datos',
  materiales: 'Minerales',
  utilities: 'Energía',
  nuclear: 'Energía',
  espacio: 'Industria aeroespacial',
  defensa: 'Industria aeroespacial',
};

export interface RelatedTheme {
  id: string;
  name: string;
}

/** Dirección inversa, con el nombre visible de cada cesta relacionada. */
export const BOTTLENECK_TO_THEMES: Record<string, RelatedTheme[]> = {
  Semiconductores: [{ id: 'semiconductores', name: 'Semiconductores' }],
  'Centros de datos': [{ id: 'centros-de-datos', name: 'Centros de datos' }],
  Minerales: [{ id: 'materiales', name: 'Materiales críticos' }],
  Energía: [
    { id: 'utilities', name: 'Energía y utilities' },
    { id: 'nuclear', name: 'Nuclear' },
  ],
  'Industria aeroespacial': [
    { id: 'espacio', name: 'Espacio' },
    { id: 'defensa', name: 'Defensa y aeroespacial' },
  ],
};
