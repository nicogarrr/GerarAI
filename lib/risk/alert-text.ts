import type { Locale } from '@/lib/i18n/locale';
import type { TranslateFn } from '@/lib/i18n/translate';

// valuation/portfolio_risk.py manda el texto de cada alerta de /risk en
// castellano. En inglés se reconoce la frase y se dice en inglés; en castellano
// (o un texto que no conocemos) se pinta tal cual.
const OVER_20 = /^(.+) supera el 20 % de peso en la cartera$/;
const PRE_FCF_OVER_10 = /^(.+) es pre-FCF y supera el 10 % de peso en la cartera$/;
const NET_CASH = /^El saldo neto de caja, convertido a (\S+), es negativo(?: \(saldo negativo en (.+)\))?$/;
const CASH = /^El saldo de caja en (\S+) es negativo$/;

export function riskAlertText(message: string, locale: Locale, t: TranslateFn): string {
  if (locale !== 'en') return message;
  let m = OVER_20.exec(message);
  if (m) return t('risk.alertText.over20', { ticker: m[1] });
  m = PRE_FCF_OVER_10.exec(message);
  if (m) return t('risk.alertText.preFcfOver10', { ticker: m[1] });
  m = NET_CASH.exec(message);
  if (m) return m[2] ? t('risk.alertText.netCashNegativeIn', { currency: m[1], detail: m[2] }) : t('risk.alertText.netCashNegative', { currency: m[1] });
  m = CASH.exec(message);
  if (m) return t('risk.alertText.cashNegative', { currency: m[1] });
  return message;
}
