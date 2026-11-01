import { formatMarketCapUsd, formatPercent } from '@/lib/format';
import type { GemReason } from '@/lib/actions/propicks-gems.actions';

/** Idioma del texto; el módulo sigue siendo puro (el componente pasa el locale). */
export type GemsLocale = 'es' | 'en';

const LABELS: Record<string, string> = {
  fcf_yield: 'Rentabilidad por FCF',
  roic_spread: 'ROIC menos WACC',
  net_debt_to_ebitda: 'Deuda neta / EBITDA',
  insider_net_buy_usd: 'Compras netas de directivos',
  managers_adding_13f: 'Gestores 13F que compran',
};

const LABELS_EN: Record<string, string> = {
    fcf_yield: 'FCF yield',
    roic_spread: 'ROIC minus WACC',
    net_debt_to_ebitda: 'Net debt / EBITDA',
    insider_net_buy_usd: 'Net insider buying',
    managers_adding_13f: '13F managers buying',
};

export function gemReasonLabel(key: string, locale: GemsLocale = 'es'): string {
    if (locale === 'en') return LABELS_EN[key] ?? key;
  return LABELS[key] ?? key;
}

/** Formato es-ES; USD con $ y porcentajes con coma decimal. */
export function gemReasonValue(reason: GemReason, locale: GemsLocale = 'es'): string {
    const tag = locale === 'en' ? 'en-US' : 'es-ES';
  switch (reason.key) {
    case 'fcf_yield':
    case 'roic_spread':
      return formatPercent(reason.value, { digits: 1 }, undefined, locale);
    case 'net_debt_to_ebitda':
      return `${new Intl.NumberFormat('es-ES', { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(reason.value)}x`;
    case 'insider_net_buy_usd':
      return formatMarketCapUsd(reason.value, undefined, locale);
    case 'managers_adding_13f': {
      // El número suelto («7») no decía qué cuenta (Tester 6): son gestores.
      const n = new Intl.NumberFormat(tag, { maximumFractionDigits: 0 }).format(reason.value);
      if (locale === 'en') return `${n} ${reason.value === 1 ? 'manager' : 'managers'}`;
            return `${n} ${reason.value === 1 ? 'gestor' : 'gestores'}`;
    }
    default:
      return new Intl.NumberFormat(tag, { maximumFractionDigits: 0 }).format(reason.value);
  }
}
