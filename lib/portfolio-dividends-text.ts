/**
 * Proyección de dividendos (dividend_projection_service.py): el backend manda
 * en castellano los supuestos fiscales, la nota de cada año, el motivo de una
 * retención sin verificar, las condiciones del escenario y la nota de los
 * dividendos declarados. En inglés se traducen; en castellano, y con un texto
 * que no se reconoce, pasa el del backend tal cual (la salvedad nunca se pierde).
 */
import type { Locale } from '@/lib/i18n/locale';

const DIVIDEND_PROJECTION_EN: Record<string, string> = {
  // Supuestos fiscales (_FISCAL_CONDITIONS)
  'Residencia fiscal en España asumida.': 'Spanish tax residence assumed.',
  'W-8BEN vigente asumido para dividendos US (sin W-8BEN el tipo sería 30 %).': 'Valid W-8BEN assumed for US dividends (without a W-8BEN the rate would be 30%).',
  'Tipo de dividendo ordinario asumido: no se verifica la categoría (REIT, ADR, ETF, PID pueden tener tratamiento distinto) y no se deduce del domicilio.':
    'Ordinary dividend type assumed: the category is not verified (REIT, ADR, ETF, PID may be treated differently) and it is not inferred from the domicile.',
  'Los tipos de retención son escenario (Anexo III AEAT: convenio US 0/15 según condiciones), no verificación particular de cada pago.':
    'Withholding rates are a scenario (AEAT Annex III: US treaty 0/15 depending on conditions), not a check of each payment.',
  'Única renta del ahorro del año asumida; el IRPF real depende del resto de la base.':
    'Assumed to be the only savings income of the year; the real IRPF (Spanish income tax) depends on the rest of the tax base.',
  'Escala del ahorro de la Renta 2025 aplicada a años futuros (hipótesis, sujeta a cambio legislativo).':
    'Savings-income scale of the 2025 tax return applied to future years (an assumption, subject to legislative change).',
  'La retención ES del 19 % es pago a cuenta, no impuesto extranjero ni deducción por doble imposición.':
    'The 19% Spanish (ES) withholding is a payment on account, not a foreign tax or a double-taxation relief.',
  'Canadá (p. ej. BN): se usa el techo del convenio ES-CA (15 %) como escenario; Canadá retiene 25 % si el broker no aplica el convenio (CRA, Part XIII), y la retención efectiva no está verificada.':
    'Canada (e.g. BN): the ES-CA treaty ceiling (15%) is used as the scenario; Canada withholds 25% if the broker does not apply the treaty (CRA, Part XIII), and the effective withholding is not verified.',
  'Emisor en Islas Caimán (p. ej. BABA): escenario 0 % = solo ley de Caimán (20-F Item 10.E); NO es la retención efectiva del broker y no cubre una posible retención china (20 % IIT condicional, convenio incierto para ADS). Las condiciones se muestran junto al importe.':
    'Issuer in the Cayman Islands (e.g. BABA): 0% scenario = Cayman law only (20-F Item 10.E); it is NOT the broker’s effective withholding and does not cover a possible Chinese withholding (20% conditional IIT, uncertain treaty for ADSs). The conditions are shown next to the amount.',
  'Emisor verificado por ticker (BN: Ontario; BABA: Islas Caimán). Domicilio de la base de datos o mercado de cotización no determinan la retención.':
    'Issuer verified by ticker (BN: Ontario; BABA: Cayman Islands). The database domicile or the listing market do not determine the withholding.',
  'Domicilios sin tipo verificado (p.ej. GB: HMRC IFM28125 distingue categorías) salen como sin datos.':
    'Domiciles without a verified rate (e.g. GB: HMRC IFM28125 distinguishes categories) are shown as no data.',
  // Nota de cada año (fiscal_by_year[año].note)
  'Sin datos': 'Data not available',
  'Sin datos: todas las posiciones con dividendo proyectado este año carecen de tipo de cambio o de retención verificada (N/D, no cero).':
    'Data not available: every position with a projected dividend this year lacks an exchange rate or a verified withholding (no data, not zero).',
  'Escenario fiscal no disponible: la divisa base no es EUR.': 'Tax scenario not available: the base currency is not EUR.',
  'Escenario condicionado (ver «Supuestos fiscales y fuentes»); no es el neto final.': 'Conditional scenario (see “Fiscal assumptions and sources”); not the final net.',
  // Retención sin verificar y condiciones del escenario
  'Emisor constituido en Islas Caimán (ADS en NYSE; la sede en Hong Kong es la que figura como domicilio en la base de datos). Sin tipo de retención verificado.':
    'Issuer incorporated in the Cayman Islands (ADSs on the NYSE; the Hong Kong headquarters is what the database shows as domicile). No verified withholding rate.',
  'Sin domicilio ni emisor verificado; retención no verificada.': 'No verified domicile or issuer; withholding not verified.',
  'Escenario 0 % = solo ley de Islas Caimán (20-F Item 10.E): sin retención en Caimán. Condiciones: Alibaba no cree ser residente fiscal en China, pero si las autoridades chinas la trataran como tal podría aplicarse 20 % de IIT a un tenedor persona física no residente, con reducción por convenio incierta para ADS. Comisiones del depositario aparte. Retención efectiva del broker: NO verificada.':
    '0% scenario = Cayman Islands law only (20-F Item 10.E): no Cayman withholding. Conditions: Alibaba does not believe it is a Chinese tax resident, but if the Chinese authorities treated it as one, 20% IIT could apply to a non-resident individual holder, with an uncertain treaty reduction for ADSs. Depositary fees are separate. Broker’s effective withholding: NOT verified.',
  // Declarados con ex_date futura
  'Declarado con ex_date futura según el proveedor de datos (no verificado contra fuente primaria); no alimenta la réplica.':
    'Declared with a future ex-date according to the data provider (not verified against a primary source); it does not feed the replica.',
  INGESTADO: 'INGESTED',
};

const SUBSET_PREFIX = 'Subconjunto cubierto: hay posiciones excluidas sin tipo de cambio o sin retención verificada (sin datos, no cero). ';
const SUBSET_PREFIX_EN = 'Covered subset: some positions are excluded for lacking an exchange rate or a verified withholding (no data, not zero). ';
const ISSUER_IN = /^Emisor en (\S+) sin tipo de retención verificado\.$/;
const DB_DOMICILE = /^Domicilio en base de datos: (\S+); sin tipo de retención verificado para ese país \(no se deduce del mercado ni se asume 0 %\)\.$/;

export function dividendProjectionText<T extends string | null | undefined>(text: T, locale: Locale): T | string {
  if (locale !== 'en' || !text) return text;
  if (Object.hasOwn(DIVIDEND_PROJECTION_EN, text)) return DIVIDEND_PROJECTION_EN[text];
  if (text.startsWith(SUBSET_PREFIX)) {
    const rest = text.slice(SUBSET_PREFIX.length);
    return SUBSET_PREFIX_EN + String(dividendProjectionText(rest, locale));
  }
  const issuer = ISSUER_IN.exec(text);
  if (issuer) return `Issuer in ${issuer[1]} with no verified withholding rate.`;
  const domicile = DB_DOMICILE.exec(text);
  if (domicile) return `Database domicile: ${domicile[1]}; no verified withholding rate for that country (not inferred from the market, and 0% is not assumed).`;
  return text;
}
