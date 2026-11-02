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

// Mismas etiquetas en inglés (Ajustes → Idioma).
const CHANGE_LABELS_EN: Record<HolderChange, string> = {
  new: 'new position',
  increased: 'adds',
  decreased: 'trims',
  unchanged: 'holds',
  closed: 'exits',
};

/** Idioma de las líneas: «es» (por defecto) o «en». */
export type OwnershipLocale = 'es' | 'en';

const usd = new Intl.NumberFormat('es-ES', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
const usdEn = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });

/** Importe en USD con formato es-ES («113.100 US$») o en-US («$113,100»). */
export function ownershipMoney(value: number, locale: OwnershipLocale = 'es'): string {
  return (locale === 'en' ? usdEn : usd).format(value);
}

export function holderChangeLabel(change: HolderChange | null | undefined, locale: OwnershipLocale = 'es'): string {
  if (locale === 'en') return change ? CHANGE_LABELS_EN[change] : 'no comparison';
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

/**
 * Textos del backend (ticker_ownership_signals.py e investor_overlap.py) que
 * llegan solo en castellano: la lectura del bloque insider y el motivo de un
 * bloque sin datos. En inglés se traducen; en castellano, y con un texto que
 * no se reconoce, pasan tal cual.
 */
const TEXT_EN: Record<string, string> = {
  'Compras en grupo de insiders (3 o más)': 'Cluster buying by insiders (3 or more)',
  'Compras netas de insiders': 'Net insider buying',
  'Ventas netas de insiders': 'Net insider selling',
  'Sin balance claro de insiders': 'No clear insider balance',
  'Sin CUSIP verificado para cruzar los 13F (emisor no estadounidense o identidad pendiente).':
    'No verified CUSIP to cross-check 13F filings (non-US issuer or identity pending).',
  'Aún no hay 13F sincronizados de los gestores revisados en tu cuenta. Se actualizan automáticamente cada lunes por la mañana.':
    'No 13F filings from the reviewed managers are synced to your account yet. They update automatically every Monday morning.',
  'No se pudo leer este bloque ahora mismo.': 'This block could not be read right now.',
  'Identidad en conflicto: la referencia no corresponde al ticker.': 'Conflicting identity: the reference does not match the ticker.',
  'Identidad en conflicto: los ISIN registrados no coinciden.': 'Conflicting identity: the recorded ISINs do not match.',
  'Referencia CUSIP inválida.': 'Invalid CUSIP reference.',
  'Identidad en conflicto: CUSIP e ISIN de la referencia.': "Conflicting identity: the reference's CUSIP and ISIN.",
  'Identidad en conflicto: CUSIP de referencia e ISIN de cartera.': 'Conflicting identity: reference CUSIP and portfolio ISIN.',
  'ISIN registrado sin CUSIP derivable verificado.': 'Recorded ISIN without a verified derivable CUSIP.',
  'ISIN de referencia sin CUSIP derivable verificado.': 'Reference ISIN without a verified derivable CUSIP.',
};

const NO_TRADES_RE = /^Sin compras ni ventas de insiders en mercado abierto \(Form 4\) persistidas para (.+) en los últimos (\d+) días\.$/;
const NOT_IN_UNIVERSE_RE = /^(.+) no está en el universo de empresas: sin cruce 13F\.$/;

/** Lectura o motivo del backend en el idioma de la pantalla. */
export function ownershipText(text: string, locale: OwnershipLocale = 'es'): string {
  if (locale !== 'en') return text;
  if (Object.hasOwn(TEXT_EN, text)) return TEXT_EN[text];
  const noTrades = NO_TRADES_RE.exec(text);
  if (noTrades) return `No open-market insider buys or sells (Form 4) stored for ${noTrades[1]} in the last ${noTrades[2]} days.`;
  const notInUniverse = NOT_IN_UNIVERSE_RE.exec(text);
  if (notInUniverse) return `${notInUniverse[1]} is not in the company universe: no 13F cross-check.`;
  return text;
}

/** Líneas legibles del bloque insider (o su motivo si no hay datos). */
export function insiderLines(block: InsiderOwnershipBlock, locale: OwnershipLocale = 'es'): string[] {
  if (block.status !== 'ok') return [block.detail ? ownershipText(block.detail, locale) : (locale === 'en' ? 'No insider data.' : 'Sin datos de insiders.')];
  const planned = block.sells.planned_10b5_1 ?? 0;
  if (locale === 'en') {
    const money = (value: number) => ownershipMoney(value, 'en');
    return [
      `Buys: ${block.buys.trades} by ${block.buys.insiders} ${block.buys.insiders === 1 ? 'insider' : 'insiders'} for ${money(block.buys.value)}.`,
      `Sells: ${block.sells.trades} by ${block.sells.insiders} ${block.sells.insiders === 1 ? 'insider' : 'insiders'} for ${money(block.sells.value)}${planned ? ` (${planned} under a 10b5-1 plan)` : ''}.`,
      `Net: ${money(block.net_value)}${block.last_date ? ` · last trade ${block.last_date}` : ''}.`,
    ];
  }
  return [
    `Compras: ${block.buys.trades} de ${block.buys.insiders} insiders por ${ownershipMoney(block.buys.value)}.`,
    `Ventas: ${block.sells.trades} de ${block.sells.insiders} insiders por ${ownershipMoney(block.sells.value)}${planned ? ` (${planned} con plan 10b5-1)` : ''}.`,
    `Saldo neto: ${ownershipMoney(block.net_value)}${block.last_date ? ` · última operación ${block.last_date}` : ''}.`,
  ];
}

/** Líneas legibles del bloque 13F (o su motivo si no hay datos). */
export function holdersLines(block: HoldersOwnershipBlock, locale: OwnershipLocale = 'es'): string[] {
  if (block.status !== 'ok') return [block.detail ? ownershipText(block.detail, locale) : (locale === 'en' ? 'No 13F data.' : 'Sin datos 13F.')];
  const { changes } = block;
  if (locale === 'en') {
    const lines = [
      `${block.holders_count} of ${block.managers_with_data} managers reviewed report it${block.report_date ? ` (13F for ${block.report_date})` : ''}${block.total_value_usd ? ` worth ${ownershipMoney(block.total_value_usd, 'en')}` : ''}.`,
      `Versus the previous quarter: ${changes.new} new, ${changes.increased} adding, ${changes.decreased} trimming, ${changes.closed} exiting.`,
    ];
    if (block.exited.length) lines.push(`Exiting: ${block.exited.join(', ')}.`);
    return lines;
  }
  const lines = [
    `${block.holders_count} de ${block.managers_with_data} gestores revisados lo declaran${block.report_date ? ` (13F de ${block.report_date})` : ''}${block.total_value_usd ? ` por ${ownershipMoney(block.total_value_usd)}` : ''}.`,
    `Frente al trimestre anterior: ${changes.new} nuevas, ${changes.increased} aumentan, ${changes.decreased} reducen, ${changes.closed} salen.`,
  ];
  if (block.exited.length) lines.push(`Salen: ${block.exited.join(', ')}.`);
  return lines;
}
