/**
 * Dominio oficial de la empresa por ticker (listado tal cual lo usa la app,
 * con sufijo de bolsa: AENA.MC, CGEO.L, 7203.T…). Solo sirve para pedir a la
 * PROPIA web de la empresa su icono cuando FMP no tiene logo para ese símbolo
 * (404, p. ej. AENA sin sufijo). Lista cerrada y revisada a mano: el dominio
 * nunca sale de la petición del usuario, así que la ruta /api/logo no puede
 * usarse para pedir URLs arbitrarias (sin SSRF).
 *
 * Añadir un ticker = una línea. Si no está aquí, la ruta prueba la web que
 * declara Finnhub para ese símbolo (si hay FINNHUB_API_KEY) y, si tampoco,
 * la UI pinta las iniciales.
 */
export const COMPANY_DOMAINS: Readonly<Record<string, string>> = {
    'ASTS': 'ast-science.com',
    'BN': 'brookfield.com',
    'RKLB': 'rocketlabusa.com',
    'UBER': 'uber.com',
    'ONDS': 'ondas.com',
    'BABA': 'alibabagroup.com',
    '9988.HK': 'alibabagroup.com',
    'KRKNF': 'krakenrobotics.com',
    'PNG.V': 'krakenrobotics.com',
    'CGEO.L': 'georgiacapital.ge',
    'CGEO': 'georgiacapital.ge',
    'CPT': 'camdenliving.com',
    'KKR': 'kkr.com',
    'POOL': 'poolcorp.com',
    'CB': 'chubb.com',
    'UNH': 'unitedhealthgroup.com',
    'HIMS': 'hims.com',
    'RXRX': 'recursion.com',
    'NAUT': 'nautilus.bio',
    'ABCL': 'abcellera.com',
    'IBRX': 'immunitybio.com',
    'AAPL': 'apple.com',
    'MSFT': 'microsoft.com',
    'GOOGL': 'google.com',
    'GOOG': 'google.com',
    'AMZN': 'amazon.com',
    'META': 'meta.com',
    'NVDA': 'nvidia.com',
    'TSLA': 'tesla.com',
    'JPM': 'jpmorganchase.com',
    'V': 'visa.com',
    'MA': 'mastercard.com',
    'KO': 'coca-colacompany.com',
    'PEP': 'pepsico.com',
    'NFLX': 'netflix.com',
    'COST': 'costco.com',
    'BRK-B': 'berkshirehathaway.com',
    'BRK-A': 'berkshirehathaway.com',
    'PLTR': 'palantir.com',
    'SOFI': 'sofi.com',
    'CRWD': 'crowdstrike.com',
    'MELI': 'mercadolibre.com',
    'NU': 'nubank.com.br',
    'TSM': 'tsmc.com',
    '2330.TW': 'tsmc.com',
    'NVO': 'novonordisk.com',
    'NOVO-B.CO': 'novonordisk.com',
    'SPOT': 'spotify.com',
    'ARM': 'arm.com',
    'RDDT': 'redditinc.com',
    'LOGI': 'logitech.com',
    'DIS': 'thewaltdisneycompany.com',
    'AENA': 'aena.es',
    'AENA.MC': 'aena.es',
    // 31-oct-2026: huecos medidos en la watchlist real de pruebas (FMP daba
    // logo y /api/logo 404). Dominios oficiales verificados uno a uno:
    // BFIT = Basic-Fit N.V. (Euronext Ámsterdam) — corporate.basic-fit.com/investors
    'BFIT': 'basic-fit.com',
    'BFIT.AS': 'basic-fit.com',
    // IBG = Iberpapel Gestión (BME) — iberpapel.es
    'IBG': 'iberpapel.es',
    'IBG.MC': 'iberpapel.es',
    // EBRO = Ebro Foods (BME) — ebrofoods.es
    'EBRO': 'ebrofoods.es',
    'EBRO.MC': 'ebrofoods.es',
    // VID = Vidrala (BME) — vidrala.com (el icono solo resuelve vía www,
    // verificado con fetchSiteIcon: bare=null, www=OK)
    'VID': 'www.vidrala.com',
    'VID.MC': 'www.vidrala.com',
    // SPCX = SpaceX (pre-IPO, sin listado oficial) — spacex.com
    'SPCX': 'spacex.com',
    'ITX.MC': 'inditex.com',
    'SAN.MC': 'santander.com',
    'SAN': 'santander.com',
    'IBE.MC': 'iberdrola.com',
    'BBVA.MC': 'bbva.com',
    'BBVA': 'bbva.com',
    'REP.MC': 'repsol.com',
    'TEF.MC': 'telefonica.com',
    'FER.MC': 'ferrovial.com',
    'FER': 'ferrovial.com',
    'CABK.MC': 'caixabank.com',
    'ACS.MC': 'grupoacs.com',
    'GRF.MC': 'grifols.com',
    'ANA.MC': 'acciona.com',
    'CLNX.MC': 'cellnex.com',
    'MC.PA': 'lvmh.com',
    'AIR.PA': 'airbus.com',
    'TTE.PA': 'totalenergies.com',
    'ASML.AS': 'asml.com',
    'ASML': 'asml.com',
    'ADYEN.AS': 'adyen.com',
    'PRX.AS': 'prosus.com',
    'SAP.DE': 'sap.com',
    'SAP': 'sap.com',
    'SIE.DE': 'siemens.com',
    'VOW3.DE': 'volkswagen-group.com',
    'NESN.SW': 'nestle.com',
    'NOVN.SW': 'novartis.com',
    'AZN.L': 'astrazeneca.com',
    'AZN': 'astrazeneca.com',
    'SHEL.L': 'shell.com',
    'SHEL': 'shell.com',
    'DGE.L': 'diageo.com',
    'RR.L': 'rolls-royce.com',
    'RACE.MI': 'ferrari.com',
    'RACE': 'ferrari.com',
    'ENEL.MI': 'enel.com',
    'EQNR.OL': 'equinor.com',
    '7203.T': 'global.toyota',
    'TM': 'global.toyota',
    '0700.HK': 'tencent.com',
    'SHOP.TO': 'shopify.com',
    'SHOP': 'shopify.com',
    'CSU.TO': 'csisoftware.com',
    'BHP.AX': 'bhp.com',
    'BHP': 'bhp.com',
    '005930.KS': 'samsung.com',
    'RELIANCE.NS': 'ril.com',
};

/** Normaliza el ticker como lo guarda la app (mayúsculas; BRK.B -> BRK-B). */
export function normalizeLogoTicker(ticker: string): string {
    const t = ticker.trim().toUpperCase();
    return /^[A-Z]{1,5}\.[AB]$/.test(t) ? t.replace('.', '-') : t;
}

export function companyDomainFor(ticker: string): string | null {
    return COMPANY_DOMAINS[normalizeLogoTicker(ticker)] ?? null;
}
