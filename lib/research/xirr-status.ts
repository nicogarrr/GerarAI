// @ts-expect-error TS5097: node --test (--experimental-strip-types) necesita la extensión.
import { t as esT, type TranslationKey, type TranslationVars } from '../i18n/t.ts';

/** Traductor del idioma elegido; por defecto el español de referencia. */
type TiFn = (key: TranslationKey, vars?: TranslationVars) => string;

/** Reasons must describe missing coverage, not invent absent transactions. */
const XIRR_ND_REASONS: Record<string, TranslationKey> = {
  incomplete_missing_fx: 'portfolio.intelligence.xirrReasons.missingFx',
  incomplete_ambiguous_cash: 'portfolio.intelligence.xirrReasons.ambiguousCash',
  incomplete_missing_cash_balance: 'portfolio.intelligence.xirrReasons.missingCashBalance',
  insufficient_cashflows: 'portfolio.intelligence.xirrReasons.insufficientCashflows',
  no_xirr_root: 'portfolio.intelligence.xirrReasons.noRoot',
};

export function xirrUnavailableReason(status: unknown, ti: TiFn = esT): string {
  const key = String(status ?? '');
  return ti(Object.hasOwn(XIRR_ND_REASONS, key) ? XIRR_ND_REASONS[key] : 'portfolio.intelligence.xirrReasons.default');
}
