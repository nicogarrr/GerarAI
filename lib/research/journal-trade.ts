/**
 * Diario de decisiones enlazado a operaciones reales (IBKR o manuales).
 *
 * Funciones puras (sin Next) para describir la operación y el valor justo de
 * ese día en es-ES. Mismo contrato que data-engine/app/services/journal_trade_link.py.
 */

export type JournalTrade = {
  id: number;
  trade_date: string;
  action: string;
  action_label?: string;
  quantity: number | null;
  price: number | null;
  fees?: number | null;
  currency: string | null;
  source?: string;
  linked_entry_ids?: number[];
};

export type JournalFairValue = {
  value: number;
  source: 'tesis' | 'motor';
  version: number | null;
  as_of: string | null;
  stale: boolean;
  label: string;
  margin_vs_trade_price: number | null;
  note: string | null;
};

const ACTION_LABELS: Record<string, string> = { buy: 'Compra', sell: 'Venta' };

function number(value: number, digits = 2): string {
  return new Intl.NumberFormat('es-ES', { minimumFractionDigits: 0, maximumFractionDigits: digits }).format(value);
}

function money(value: number): string {
  return new Intl.NumberFormat('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
}

/** «12/03/2026» a partir de «2026-03-12» (día de calendario, sin zona). */
export function dayEs(isoDay: string | null | undefined): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(isoDay ?? '');
  return match ? `${match[3]}/${match[2]}/${match[1]}` : 's/d';
}

/** «Compra 10 @ 70,50 USD · 12/03/2026». */
export function describeTrade(trade: JournalTrade): string {
  const label = trade.action_label ?? ACTION_LABELS[trade.action] ?? trade.action;
  const qty = trade.quantity != null ? ` ${number(trade.quantity, 4)}` : '';
  const price = trade.price != null ? ` @ ${money(trade.price)}${trade.currency ? ` ${trade.currency}` : ''}` : '';
  return `${label}${qty}${price} · ${dayEs(trade.trade_date)}`;
}

/** «Valor justo ese día: 90,00 (Tesis publicada v1, 10/01/2026) · margen +25,0 %». */
export function describeFairValue(reading: JournalFairValue | null | undefined): string {
  if (!reading) return 'Valor justo ese día: sin valoración previa a la operación.';
  const origin = reading.as_of ? `${reading.label}, ${dayEs(reading.as_of)}` : reading.label;
  let text = `Valor justo ese día: ${money(reading.value)} (${origin})`;
  if (reading.margin_vs_trade_price != null) {
    const pct = new Intl.NumberFormat('es-ES', {
      style: 'percent',
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
      signDisplay: 'exceptZero',
    }).format(reading.margin_vs_trade_price);
    text += ` · margen ${pct.replace(/\u00a0/g, ' ')}`;
  } else if (reading.note) {
    text += ` · ${reading.note}`;
  }
  return text;
}
