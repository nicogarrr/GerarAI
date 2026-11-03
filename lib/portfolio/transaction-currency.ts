/** Preserve the case-sensitive pence code before normalizing ISO currencies.
 * GBp is 1/100 GBP; uppercasing it changes the amount of an imported trade.
 * Other minor-unit aliases (ZAc/ILa) remain minor units when uppercased.
 * Keep this boundary aligned with backend canonical_currency_code.
 */
export function transactionCurrencyCode(currency: string): string {
    const code = currency.trim();
    return code === 'GBp' ? code : code.toUpperCase();
}
