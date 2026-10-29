/**
 * Asistente por intención (WorldStocks punto 4): Entender / Revisar supuestos /
 * Cuestionar. Cada intención es una PREGUNTA guiada que se envía al chat con
 * contrato de evidencia de siempre; ninguna inventa contenido: piden
 * hechos/cálculos, hipótesis con su evidencia o contradicciones, que es lo
 * que ese contrato ya secciona.
 */
export const CHAT_INTENTS = [
  {
    key: 'entender',
    label: 'Entender',
    question: (t: string) => `¿Qué hace ${t}, cómo gana dinero y qué hechos y cálculos hay registrados sobre la empresa?`,
  },
  {
    key: 'supuestos',
    label: 'Revisar supuestos',
    question: (t: string) => `¿Qué supuestos e hipótesis sostienen la tesis de ${t} y qué evidencia tiene cada uno?`,
  },
  {
    key: 'cuestionar',
    label: 'Cuestionar',
    question: (t: string) => `¿Qué contradicciones, datos insuficientes y evidencia en contra hay registrados sobre ${t}?`,
  },
] as const;

/** URL del chat de la ficha con la pregunta de la intención ya puesta. */
export function chatIntentHref(ticker: string, intent: (typeof CHAT_INTENTS)[number]): string {
  return `/research/${encodeURIComponent(ticker)}?view=fuentes&chat=${encodeURIComponent(intent.question(ticker))}#chat`;
}
