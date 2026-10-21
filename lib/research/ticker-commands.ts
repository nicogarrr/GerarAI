/**
 * Comandos de ficha tipo terminal (referencia Bloomberg): `<TICKER> <FUNCION>`
 * en el buscador (Ctrl+K) abre la vista directa de la empresa sin tocar el
 * raton: `ASTS FA` -> financieros, `ASTS N` -> noticias, etc.
 *
 * Cada comando apunta a una ruta que YA existe (vista `?view=` de la ficha,
 * subruta propia, ancla de la cabecera o el gestor de alertas); ningun
 * comando inventa una pagina. El ancla `#grafico` la expone la propia ficha.
 * ALERT lleva a `/alerts?symbol=<ticker>`, el deep-link que ya usa
 * QuickAlertButton: el gestor abre el dialogo de creacion pre-rellenado y
 * no se crea nada hasta el envio explicito del formulario por el usuario.
 *
 * Test funcional: scripts/ticker-commands-guard.test.ts.
 */
export type TickerCommand = {
  /** Codigo corto tal como se teclea, en mayusculas (`FA`). */
  code: string;
  /** Nombre visible del destino, en espanol. */
  label: string;
  /** Destino dentro de la app para el ticker ya normalizado (mayusculas). */
  href: (ticker: string) => string;
};

export const TICKER_COMMANDS: readonly TickerCommand[] = [
  { code: 'DES', label: 'Visión general', href: (t) => `/research/${encodeURIComponent(t)}` },
  { code: 'FA', label: 'Financieros', href: (t) => `/research/${encodeURIComponent(t)}?view=financials` },
  { code: 'HDS', label: 'Propietarios, 13F e insiders', href: (t) => `/research/${encodeURIComponent(t)}?view=holders` },
  { code: 'N', label: 'Noticias', href: (t) => `/research/news?ticker=${encodeURIComponent(t)}` },
  { code: 'GP', label: 'Gráfico', href: (t) => `/research/${encodeURIComponent(t)}#grafico` },
  { code: 'TESIS', label: 'Tesis', href: (t) => `/research/${encodeURIComponent(t)}/tesis` },
  { code: 'ALERT', label: 'Alertas', href: (t) => `/alerts?symbol=${encodeURIComponent(t)}` },
] as const;

export type TickerCommandQuery = {
  /** Ticker normalizado en mayusculas tal como se tecleo. */
  ticker: string;
  /** Comandos cuyo codigo empieza por el prefijo tecleado (todos si aun no hay prefijo). */
  matches: TickerCommand[];
  /** Comando cuyo codigo coincide exactamente con lo tecleado, si existe. */
  exact: TickerCommand | null;
};

/**
 * `<ticker> <prefijo de funcion>`: el ticker es el primer token (letras,
 * digitos, punto o guion; cubre BRK.B y SAN.MC) y el prefijo son hasta 5
 * letras. Sin segundo token no es un comando: "ASTS" solo sigue siendo una
 * busqueda normal de acciones.
 */
const COMMAND_PATTERN = /^\s*([A-Za-z][A-Za-z0-9.-]{0,11})\s+([A-Za-z]{0,5})\s*$/;

/**
 * Interpreta el texto del buscador como comando de ficha. Devuelve null cuando
 * el texto no tiene forma de comando o el prefijo no corresponde a ninguna
 * funcion conocida: en ambos casos el buscador se comporta como siempre.
 */
export function parseTickerCommand(query: string): TickerCommandQuery | null {
  const match = COMMAND_PATTERN.exec(query);
  if (!match) return null;
  const ticker = match[1].toUpperCase();
  const prefix = match[2].toUpperCase();
  const matches = TICKER_COMMANDS.filter((command) => command.code.startsWith(prefix));
  if (matches.length === 0) return null;
  const exact = prefix.length > 0 ? (matches.find((command) => command.code === prefix) ?? null) : null;
  return { ticker, matches, exact };
}
