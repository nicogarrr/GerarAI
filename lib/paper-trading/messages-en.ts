/**
 * Mensajes de la cuenta demo (validación de opciones, server actions de
 * órdenes y conversiones) en inglés para Ajustes → Idioma = English.
 * Las reglas y sus textos en español viven donde se validan; aquí solo se
 * traduce el texto ya decidido. Lo que no se reconoce pasa tal cual.
 */

const EXACT_EN: Record<string, string> = {
  // lib/paper-trading/options.ts
  'Contrato de opción ausente.': 'The option contract is missing.',
  'Subyacente inválido.': 'Invalid underlying.',
  'Tipo debe ser call o put.': 'Type must be call or put.',
  'Strike debe ser un número mayor que 0.': 'Strike must be a number greater than 0.',
  'Vencimiento inválido (se espera yyyy-mm-dd real).': 'Invalid expiry (a real yyyy-mm-dd date is expected).',
  'Solo se admite entrega de acciones en fase 1.': 'Only share delivery is supported in phase 1.',
  'Contrato ajustado por una operacion corporativa: no soportado en fase 1 (el deliverable y el multiplicador cambian y no se modelan).':
    'Contract adjusted for a corporate action: not supported in phase 1 (the deliverable and multiplier change and are not modelled).',
  'Solo se admiten contratos estándar con multiplicador 100.': 'Only standard contracts with a 100 multiplier are supported.',
  'Fase 1 solo admite comprar para abrir y vender para cerrar (sin vender para abrir ni cortos).':
    'Phase 1 only supports buy to open and sell to close (no sell to open or short positions).',
  'Los contratos deben ser un entero mayor que 0.': 'Contracts must be a whole number greater than 0.',
  'La prima debe ser mayor que 0.': 'The premium must be greater than 0.',
  'Divisa no soportada.': 'Unsupported currency.',
  'La comisión no puede ser negativa.': 'The fee cannot be negative.',
  'Fecha de ejecución inválida.': 'Invalid execution date.',
  'Falta clientOrderId.': 'clientOrderId is missing.',
  'El contrato ya venció en la fecha de ejecución indicada.': 'The contract had already expired on the execution date given.',
  'Sin cierre fechado del subyacente: no se asume si venció dentro o fuera del dinero.':
    'No dated close for the underlying: in or out of the money at expiry is not assumed.',
  'Dentro del dinero al vencer: ejercicio/asignación no modelados en fase 1; registra el cierre manualmente.':
    'In the money at expiry: exercise/assignment is not modelled in phase 1; record the close manually.',
  // lib/actions/manual-demo.actions.ts
  'Inicia sesión para usar la cuenta demo.': 'Sign in to use the demo account.',
  'clientOrderId debe ser una cadena de 8 a 80 caracteres (letras, dígitos, - y _).':
    'clientOrderId must be a string of 8 to 80 characters (letters, digits, - and _).',
  'El precio debe ser mayor que 0, con 4 decimales como máximo.': 'The price must be greater than 0, with at most 4 decimals.',
  'La comisión no puede ser negativa y admite 2 decimales como máximo.': 'The fee cannot be negative and allows at most 2 decimals.',
  'executedAt debe ser la fecha de ejecución en milisegundos epoch UTC, no futura.':
    'executedAt must be the execution date in UTC epoch milliseconds, not in the future.',
  'Símbolo de acción inválido (letras, dígitos, punto y guion; máx. 20).': 'Invalid stock symbol (letters, digits, dot and hyphen; max. 20).',
  'La opción necesita su contrato completo.': 'The option needs its full contract.',
  'La conversión debe ser un objeto.': 'The conversion must be an object.',
  'Origen y destino no pueden ser la misma divisa: convertir EUR en EUR crearía dinero ficticio.':
    'Source and target cannot be the same currency: converting EUR into EUR would create fictitious money.',
  'El importe debe ser mayor que 0, con 2 decimales como máximo.': 'The amount must be greater than 0, with at most 2 decimals.',
  'El tipo de cambio debe ser mayor que 0, con 6 decimales como máximo.': 'The exchange rate must be greater than 0, with at most 6 decimals.',
  'Ese identificador de orden ya se usó con una operación distinta. Recarga la página para generar uno nuevo.':
    'That order ID was already used for a different operation. Reload the page to generate a new one.',
  'No se pudo completar la operación. Inténtalo de nuevo en unos minutos.': 'The operation could not be completed. Please retry in a few minutes.',
  'La orden debe ser un objeto.': 'The order must be an object.',
  'La cantidad debe ser un entero entre 1 y 1.000.000 (sin fracciones en fase 1).': 'The quantity must be a whole number between 1 and 1,000,000 (no fractions in phase 1).',
  'Falta el instrumento.': 'The instrument is missing.',
  'executedAt debe ser la fecha en milisegundos epoch UTC, no futura.': 'executedAt must be the date in UTC epoch milliseconds, not in the future.',
  'La cuenta demo no puede operar con seguridad en este despliegue (sin transacciones). Aviso registrado.':
    'The demo account cannot trade safely on this deployment (no transactions). Warning logged.',
  'Los datos de la orden no forman un fill válido.': 'The order data do not make a valid fill.',
  'La cuenta estaba procesando otra orden a la vez. Inténtalo de nuevo.': 'The account was processing another order at the same time. Please retry.',
  'La cuenta estaba procesando otra operación a la vez. Inténtalo de nuevo.': 'The account was processing another operation at the same time. Please retry.',
};

/** Textos con cifras: el patrón español y su versión inglesa. */
const PATTERNS_EN: Array<[RegExp, (m: RegExpMatchArray) => string]> = [
  [
    /^Saldo (\w+) insuficiente: la compra cuesta (.+?) y hay (.+?)\. Si es en USD, convierte EUR antes \(conversión manual simulada\)\.$/,
    (m) => `Insufficient ${m[1]} balance: the purchase costs ${m[2]} and there is ${m[3]}. If it is in USD, convert EUR first (simulated manual conversion).`,
  ],
  [
    /^No puedes vender (.+?) acciones de (.+?): la posición en (\w+) es (.+?)\.$/,
    (m) => `You cannot sell ${m[1]} shares of ${m[2]}: the ${m[3]} position is ${m[4]}.`,
  ],
  [
    /^La comisión \((.+?)\) supera el efectivo disponible tras la venta \((.+?)\): la demo no admite sobregiro\.$/,
    (m) => `The fee (${m[1]}) exceeds the cash available after the sale (${m[2]}): the demo does not allow overdrafts.`,
  ],
  [
    /^La operación no cuadra en su fecha de ejecución \(el libro se recalcula por fecha, no por orden de alta\): ([\s\S]+)$/,
    (m) => `The operation does not balance on its execution date (the ledger is recalculated by date, not by entry order): ${m[1]}`,
  ],
];

export function paperTradingMessage(text: string, locale: 'es' | 'en' = 'es'): string {
  if (locale !== 'en' || !text) return text;
  const exact = EXACT_EN[text];
  if (exact) return exact;
  for (const [pattern, render] of PATTERNS_EN) {
    const match = text.match(pattern);
    if (match) return render(match);
  }
  return text;
}
