/**
 * Insiders (Form 4) y fondos 13F de un ticker para la ficha (conexión 10b).
 *
 * Tipos del endpoint /api/insider/ownership-signals y su traducción a líneas
 * en español. Funciones puras, sin dependencias, para poder probarlas con
 * node --test.
 */

export type InsiderSide = { trades: number; insiders: number; shares: number; value: number; planned_10b5_1?: number };

export type InsiderOwnershipBlock =
  | {
      status: 'ok';
      window_days: number;
      source: string;
      buys: InsiderSide;
      sells: InsiderSide;
      net_value: number;
      cluster_buying: boolean;
      last_date: string | null;
      reading: string;
    }
  | { status: 'sin_datos' | 'pendiente'; detail?: string; window_days?: number; source?: string };

export type HolderChange = 'new' | 'increased' | 'decreased' | 'unchanged' | 'closed';

export type HoldersOwnershipBlock =
  | {
      status: 'ok';
      source: string;
      holders_count: number;
      managers_with_data: number;
      report_date: string | null;
      total_value_usd: number | null;
      changes: { new: number; increased: number; decreased: number; closed: number };
      top_holders: { name: string; value_usd: number | null; change: HolderChange | null }[];
      exited: string[];
      limitations: string[];
    }
  | { status: 'sin_datos' | 'pendiente'; detail?: string; source?: string };

export type OwnershipSignals = { ticker: string; insider: InsiderOwnershipBlock; holders: HoldersOwnershipBlock };

export type OwnershipTone = 'positivo' | 'negativo' | 'neutro';

const CHANGE_LABELS: Record<HolderChange, string> = {
  new: 'nueva posición',
  increased: 'aumenta',
  decreased: 'reduce',
  unchanged: 'mantiene',
  closed: 'sale',
};

const usd = new Intl.NumberFormat('es-ES', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });

/** Importe en USD con formato es-ES («113.100 US$»). */
export function ownershipMoney(value: number): string {
  return usd.format(value);
}

export function holderChangeLabel(change: HolderChange | null | undefined): string {
  return change ? CHANGE_LABELS[change] : 'sin comparación';
}

/** Tono del bloque insider: compras en grupo o netas = positivo; ventas netas = negativo. */
export function insiderTone(block: InsiderOwnershipBlock): OwnershipTone {
  if (block.status !== 'ok') return 'neutro';
  if (block.cluster_buying || block.net_value > 0) return 'positivo';
  if (block.net_value < 0) return 'negativo';
  return 'neutro';
}

/** Tono 13F: más entradas/aumentos que salidas/reducciones = positivo. */
export function holdersTone(block: HoldersOwnershipBlock): OwnershipTone {
  if (block.status !== 'ok') return 'neutro';
  const up = block.changes.new + block.changes.increased;
  const down = block.changes.decreased + block.changes.closed;
  if (up > down) return 'positivo';
  if (down > up) return 'negativo';
  return 'neutro';
}

/** Líneas legibles del bloque insider (o su motivo si no hay datos). */
export function insiderLines(block: InsiderOwnershipBlock): string[] {
  if (block.status !== 'ok') return [block.detail ?? 'Sin datos de insiders.'];
  const planned = block.sells.planned_10b5_1 ?? 0;
  return [
    `Compras: ${block.buys.trades} de ${block.buys.insiders} insiders por ${ownershipMoney(block.buys.value)}.`,
    `Ventas: ${block.sells.trades} de ${block.sells.insiders} insiders por ${ownershipMoney(block.sells.value)}${planned ? ` (${planned} con plan 10b5-1)` : ''}.`,
    `Saldo neto: ${ownershipMoney(block.net_value)}${block.last_date ? ` · última operación ${block.last_date}` : ''}.`,
  ];
}

/** Líneas legibles del bloque 13F (o su motivo si no hay datos). */
export function holdersLines(block: HoldersOwnershipBlock): string[] {
  if (block.status !== 'ok') return [block.detail ?? 'Sin datos 13F.'];
  const { changes } = block;
  const lines = [
    `${block.holders_count} de ${block.managers_with_data} gestores revisados lo declaran${block.report_date ? ` (13F de ${block.report_date})` : ''}${block.total_value_usd ? ` por ${ownershipMoney(block.total_value_usd)}` : ''}.`,
    `Frente al trimestre anterior: ${changes.new} nuevas, ${changes.increased} aumentan, ${changes.decreased} reducen, ${changes.closed} salen.`,
  ];
  if (block.exited.length) lines.push(`Salen: ${block.exited.join(', ')}.`);
  return lines;
}
