import { formatMarketCapUsd, formatPercent } from '@/lib/format';
import type { GemReason } from '@/lib/actions/propicks-gems.actions';

const LABELS: Record<string, string> = {
  fcf_yield: 'Rentabilidad por FCF',
  roic_spread: 'ROIC menos WACC',
  net_debt_to_ebitda: 'Deuda neta / EBITDA',
  insider_net_buy_usd: 'Compras netas de directivos',
  managers_adding_13f: 'Gestores 13F que compran',
};

export function gemReasonLabel(key: string): string {
  return LABELS[key] ?? key;
}

/** Formato es-ES; USD con $ y porcentajes con coma decimal. */
export function gemReasonValue(reason: GemReason): string {
  switch (reason.key) {
    case 'fcf_yield':
    case 'roic_spread':
      return formatPercent(reason.value, { digits: 1 });
    case 'net_debt_to_ebitda':
      return `${new Intl.NumberFormat('es-ES', { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(reason.value)}x`;
    case 'insider_net_buy_usd':
      return formatMarketCapUsd(reason.value);
    default:
      return new Intl.NumberFormat('es-ES', { maximumFractionDigits: 0 }).format(reason.value);
  }
}
