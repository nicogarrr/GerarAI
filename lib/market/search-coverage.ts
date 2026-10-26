// Cobertura de FICHA según el plan de datos actual, no del instrumento.
// Confirmado contra la API el 26 oct 2026 (plan Finnhub gratuito):
//   - profile2 devuelve 403 «You don't have access» para SAF.PA y SAN.MC
//     (bolsas no US), 200 para META (US).
//   - /search sí cubre esas bolsas: el buscador puede ofrecer instrumentos
//     cuya ficha la app no puede comprobar.
// Regla honesta: solo se declara «plan-limited» con causa confirmada (sufijo
// de bolsa conocida no-US sin cobertura local del master); un sufijo
// desconocido queda «unknown» y no se adivina.

// Mismo mapa de sufijos que usa el buscador para etiquetar la bolsa.
export const EXCHANGE_LABEL_BY_SUFFIX: Record<string, string> = {
    MC: 'BME', // Bolsa de Madrid
    L: 'LSE',
    PA: 'Euronext Paris',
    AS: 'Euronext Amsterdam',
    BR: 'Euronext Brussels',
    LS: 'Euronext Lisbon',
    DE: 'XETRA',
    F: 'Frankfurt',
    MI: 'Borsa Italiana',
    SW: 'SIX',
    VI: 'Wiener Borse',
    HE: 'Nasdaq Helsinki',
    ST: 'Nasdaq Stockholm',
    CO: 'Nasdaq Copenhagen',
    OL: 'Oslo Bors',
    HK: 'HKEX',
    T: 'TSE',
    AX: 'ASX',
    TO: 'TSX',
    V: 'TSXV',
    MX: 'BMV',
    SA: 'B3',
    SS: 'Shanghai',
    SZ: 'Shenzhen',
    JK: 'IDX',
    HM: 'Hamburg',
    SN: 'Santiago',
};

export type FichaCoverage = 'covered' | 'plan-limited' | 'unknown';

// Sufijos con 403 de profile2 CONFIRMADO contra la API (26 oct 2026).
// No se extrapola a otras bolsas: cada sufijo nuevo necesita su evidencia.
export const PROFILE2_FORBIDDEN_SUFFIXES = new Set(['PA', 'MC']);

/**
 * Clasifica si la ficha de un resultado de búsqueda es servible.
 * `locallyCovered` = el símbolo está en el listado local verificado (master
 * CNMV .MC); esos cargan aunque profile2 no los cubra. Un no-US fuera del
 * master puede existir en el master del backend: por eso el aviso es de
 * posibilidad («puede que no tenga ficha»), nunca de inservibilidad segura.
 */
export function classifyFichaCoverage(symbol: string, locallyCovered: boolean): FichaCoverage {
    if (locallyCovered) return 'covered';
    const idx = symbol.lastIndexOf('.');
    // Sin sufijo: mercado US, cubierto por profile2 en el plan actual.
    if (idx < 0) return 'covered';
    const suffix = symbol.slice(idx + 1).toUpperCase();
    // Solo sufijos con 403 confirmado (PROFILE2_FORBIDDEN_SUFFIXES).
    if (PROFILE2_FORBIDDEN_SUFFIXES.has(suffix)) return 'plan-limited';
    // Resto (conocidos sin evidencia propia o desconocidos): no se adivina.
    return 'unknown';
}
