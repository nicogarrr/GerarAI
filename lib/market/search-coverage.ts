// Cobertura de FICHA de un resultado de búsqueda, sin extrapolar.
// Regla (main, 26 oct 2026): «covered» solo con cobertura local verificada
// (listado CNMV del master); todo lo demás es «unknown», incluido US no
// verificado. Dos GET 403 a profile2 (SAF.PA, SAN.MC) no autorizan a
// etiquetar una bolsa entera ni a atribuir la causa al plan.

// Mapa de sufijos usado por el buscador para ETIQUETAR la bolsa (display),
// no para decidir cobertura.
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

export type FichaCoverage = 'covered' | 'unknown';

/**
 * `locallyCovered` = el símbolo está en el listado local verificado (master
 * CNMV .MC). Sin esa evidencia individual la cobertura es desconocida y se
 * comunica como tal, sin atribuir causa ni prometer inservibilidad.
 */
export function classifyFichaCoverage(symbol: string, locallyCovered: boolean): FichaCoverage {
    return locallyCovered ? 'covered' : 'unknown';
}
