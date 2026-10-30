/**
 * Divisas de una operación de cartera (alta y edición manual).
 *
 * La lista incluye las nórdicas y PLN: con solo las 9 principales, una
 * operación de Estocolmo, Copenhague, Oslo o Varsovia no tenía su divisa.
 */
export const TRANSACTION_CURRENCIES = [
  'USD', 'EUR', 'GBP', 'JPY', 'CNY', 'HKD', 'CHF', 'CAD', 'AUD', 'SEK', 'DKK', 'NOK', 'PLN',
];

// Divisa probable según el sufijo de mercado del ticker (B5): al elegir
// SAN.MC la moneda no puede quedarse en USD por defecto. El usuario puede
// cambiarla después; esto solo fija un default razonable. Debe coincidir con
// `SUFFIX_QUOTE_UNIT` del backend (data-engine/app/valuation/currency.py):
// antes .ST, .CO y .OL salían en EUR y una compra de Volvo a 250 SEK se
// guardaba como 250 € (unas 10 veces más).
const SUFFIX_CURRENCY: Record<string, string> = {
  MC: 'EUR', PA: 'EUR', AS: 'EUR', BR: 'EUR', LS: 'EUR', DE: 'EUR',
  F: 'EUR', MI: 'EUR', VI: 'EUR', HE: 'EUR', IR: 'EUR', DU: 'EUR', HM: 'EUR', MU: 'EUR',
  ST: 'SEK', CO: 'DKK', OL: 'NOK', WA: 'PLN',
  L: 'GBP', IL: 'GBP', SW: 'CHF', VX: 'CHF', TO: 'CAD', V: 'CAD',
  HK: 'HKD', T: 'JPY', AX: 'AUD', SS: 'CNY', SZ: 'CNY',
};

export function defaultCurrencyFor(symbol: string): string | null {
  const idx = symbol.lastIndexOf('.');
  if (idx < 0) return null;
  return SUFFIX_CURRENCY[symbol.slice(idx + 1).toUpperCase()] ?? null;
}

/** Divisa inicial del formulario de alta: un ticker sin sufijo cotiza en EE. UU. */
export const NEW_TRANSACTION_CURRENCY = 'USD';

/** Divisa propuesta al elegir ticker: la de su bolsa, o la inicial si no tiene sufijo. */
export function currencyForTicker(symbol: string): string {
  return defaultCurrencyFor(symbol) ?? NEW_TRANSACTION_CURRENCY;
}

/** Opciones del selector: la divisa actual siempre aparece aunque no esté en la lista. */
export function currencyOptions(current: string): string[] {
  return TRANSACTION_CURRENCIES.includes(current) ? TRANSACTION_CURRENCIES : [current, ...TRANSACTION_CURRENCIES];
}

export const SUFFIX_CURRENCY_FOR_TESTS = SUFFIX_CURRENCY;
