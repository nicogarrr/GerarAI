/**
 * Proyección de dividendos (dividend_projection_service.py): el backend manda
 * en castellano los supuestos fiscales, la nota de cada año, el motivo de una
 * retención sin verificar, las condiciones del escenario y la nota de los
 * dividendos declarados. En inglés se traducen; en castellano, y con un texto
 * que no se reconoce, pasa el del backend tal cual (la salvedad nunca se pierde).
 *
 * Los textos viven en los diccionarios (portfolio.dividendProjectionBackendText,
 * patrón flow-text): el castellano es la clave de cruce con el backend y el
 * inglés su traducción. Import relativo con atributo por los tests con
 * node --experimental-strip-types.
 */
import type { Locale } from '@/lib/i18n/locale';
import esPortfolio from './i18n/messages/es/portfolio.json' with { type: 'json' };
import enPortfolio from './i18n/messages/en/portfolio.json' with { type: 'json' };

// Uso por literal para el guard de i18n (claves consumidas por objeto).
export const PORTFOLIO_DIVIDENDS_KEY_LITERALS = [
  'portfolio.dividendProjectionBackendText.taxResidence',
  'portfolio.dividendProjectionBackendText.w8ben',
  'portfolio.dividendProjectionBackendText.ordinaryType',
  'portfolio.dividendProjectionBackendText.withholdingRatesScenario',
  'portfolio.dividendProjectionBackendText.onlySavingsIncome',
  'portfolio.dividendProjectionBackendText.savingsScale',
  'portfolio.dividendProjectionBackendText.esWithholdingOnAccount',
  'portfolio.dividendProjectionBackendText.canadaTreatyCeiling',
  'portfolio.dividendProjectionBackendText.caymanZeroScenarioNote',
  'portfolio.dividendProjectionBackendText.issuerVerifiedByTicker',
  'portfolio.dividendProjectionBackendText.domicileWithoutVerifiedRate',
  'portfolio.dividendProjectionBackendText.noData',
  'portfolio.dividendProjectionBackendText.noDataAllMissing',
  'portfolio.dividendProjectionBackendText.scenarioNotAvailableCurrency',
  'portfolio.dividendProjectionBackendText.conditionalScenario',
  'portfolio.dividendProjectionBackendText.caymanIssuerNoVerifiedRate',
  'portfolio.dividendProjectionBackendText.noDomicileNoVerifiedRate',
  'portfolio.dividendProjectionBackendText.caymanZeroScenarioConditions',
  'portfolio.dividendProjectionBackendText.declaredFutureExDate',
  'portfolio.dividendProjectionBackendText.ingested',
  'portfolio.dividendProjectionBackendText.subsetPrefix',
  'portfolio.dividendProjectionBackendText.issuerInTemplate',
  'portfolio.dividendProjectionBackendText.dbDomicileTemplate',
] as const;

const ES = esPortfolio.dividendProjectionBackendText;
const EN = enPortfolio.dividendProjectionBackendText;

// Mapa exacto texto backend -> inglés; la clave es el literal del backend,
// referenciado desde el diccionario es para que el guard no lo marque huérfano.
const DIVIDEND_PROJECTION_EN: Record<string, string> = {
  [ES.taxResidence]: EN.taxResidence,
  [ES.w8ben]: EN.w8ben,
  [ES.ordinaryType]: EN.ordinaryType,
  [ES.withholdingRatesScenario]: EN.withholdingRatesScenario,
  [ES.onlySavingsIncome]: EN.onlySavingsIncome,
  [ES.savingsScale]: EN.savingsScale,
  [ES.esWithholdingOnAccount]: EN.esWithholdingOnAccount,
  [ES.canadaTreatyCeiling]: EN.canadaTreatyCeiling,
  [ES.caymanZeroScenarioNote]: EN.caymanZeroScenarioNote,
  [ES.issuerVerifiedByTicker]: EN.issuerVerifiedByTicker,
  [ES.domicileWithoutVerifiedRate]: EN.domicileWithoutVerifiedRate,
  [ES.noData]: EN.noData,
  [ES.noDataAllMissing]: EN.noDataAllMissing,
  [ES.scenarioNotAvailableCurrency]: EN.scenarioNotAvailableCurrency,
  [ES.conditionalScenario]: EN.conditionalScenario,
  [ES.caymanIssuerNoVerifiedRate]: EN.caymanIssuerNoVerifiedRate,
  [ES.noDomicileNoVerifiedRate]: EN.noDomicileNoVerifiedRate,
  [ES.caymanZeroScenarioConditions]: EN.caymanZeroScenarioConditions,
  [ES.declaredFutureExDate]: EN.declaredFutureExDate,
  [ES.ingested]: EN.ingested,
};

const SUBSET_PREFIX = ES.subsetPrefix;
const SUBSET_PREFIX_EN = EN.subsetPrefix;

// Plantillas con {domicilio}: el estático va al diccionario y la regex se
// deriva de ella para que solo haya una fuente del texto.
const TEMPLATE_VAR = '{domicilio}';
const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const templateToRegex = (tpl: string): RegExp => {
  const [pre, post] = tpl.split(TEMPLATE_VAR);
  return new RegExp(`^${escapeRegExp(pre)}(\\S+)${escapeRegExp(post)}$`);
};
const ISSUER_IN = templateToRegex(ES.issuerInTemplate);
const DB_DOMICILE = templateToRegex(ES.dbDomicileTemplate);
const renderTemplate = (tpl: string, value: string) => tpl.replace(TEMPLATE_VAR, value);

export function dividendProjectionText<T extends string | null | undefined>(text: T, locale: Locale): T | string {
  if (locale !== 'en' || !text) return text;
  if (Object.hasOwn(DIVIDEND_PROJECTION_EN, text)) return DIVIDEND_PROJECTION_EN[text];
  if (text.startsWith(SUBSET_PREFIX)) {
    const rest = text.slice(SUBSET_PREFIX.length);
    return SUBSET_PREFIX_EN + String(dividendProjectionText(rest, locale));
  }
  const issuer = ISSUER_IN.exec(text);
  if (issuer) return renderTemplate(EN.issuerInTemplate, issuer[1]);
  const domicile = DB_DOMICILE.exec(text);
  if (domicile) return renderTemplate(EN.dbDomicileTemplate, domicile[1]);
  return text;
}
