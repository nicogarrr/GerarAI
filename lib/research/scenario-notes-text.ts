/**
 * Notas N/D de los escenarios de valoración (ficha → Valoración). Los motores
 * las guardan en castellano y con la cifra en formato español
 * (valuation/engines/base.py scenario_value_or_nd y expected_value_or_nd;
 * standard_dcf.py _scenario_nd_note y el esperado). En inglés se traducen las
 * frases conocidas; en castellano, o con un texto que no se reconoce, pasa la
 * nota tal cual.
 */
import { naFor } from '@/lib/format';
import type { Locale } from '@/lib/i18n/locale';

const NA_EN = naFor('en');

const SCENARIO_EN: Record<string, string> = { bajista: 'bear', base: 'base', alcista: 'bull' };
const NUM = '(-?\\d+(?:,\\d+)?)';
const NEGATIVE = 'Una cifra negativa no es una valoración publicable: N/D\\. El valor esperado sí la tiene en cuenta\\.';
const NEGATIVE_EN = `A negative figure is not a publishable valuation: ${NA_EN}. The expected value does take it into account.`;

const PATTERNS: [RegExp, (m: RegExpExecArray, scenario: string) => string][] = [
  [/^Escenario (\S+): el modelo no produjo un valor por acción calculable: N\/D\.$/, (_m, s) => `${s} scenario: the model did not produce a computable value per share: ${NA_EN}.`],
  [new RegExp(`^Escenario (\\S+): con el margen FCF de este escenario \\(${NUM}\\s%\\) la empresa quema más caja de la que genera y el valor por acción sale ${NUM}\\. ${NEGATIVE}$`),
    (m, s) => `${s} scenario: with this scenario's FCF margin (${num(m[2])}%) the company burns more cash than it generates and the value per share comes out at ${num(m[3])}. ${NEGATIVE_EN}`],
  [new RegExp(`^Escenario (\\S+): la deuda y las obligaciones superan el valor del negocio en este escenario y el valor por acción sale ${NUM}\\. ${NEGATIVE}$`),
    (m, s) => `${s} scenario: debt and obligations exceed the value of the business in this scenario and the value per share comes out at ${num(m[2])}. ${NEGATIVE_EN}`],
  [new RegExp(`^Escenario (\\S+): Con los supuestos de este escenario el valor por acción sale ${NUM}\\. ${NEGATIVE}$`),
    (m, s) => `${s} scenario: with this scenario's assumptions the value per share comes out at ${num(m[2])}. ${NEGATIVE_EN}`],
];
const EXPECTED = new RegExp(`^El valor esperado \\(ponderado por probabilidad\\) sale ${NUM} con estos supuestos: N/D, no se publica una cifra negativa\\.$`);

function num(value: string): string {
  return value.replace(',', '.');
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function scenarioNoteText(note: string, locale: Locale): string {
  if (locale !== 'en') return note;
  const expected = EXPECTED.exec(note);
  if (expected) return `The expected (probability-weighted) value comes out at ${num(expected[1])} with these assumptions: ${NA_EN}, a negative figure is not published.`;
  for (const [pattern, render] of PATTERNS) {
    const match = pattern.exec(note);
    if (match && Object.hasOwn(SCENARIO_EN, match[1])) return capitalize(render(match, SCENARIO_EN[match[1]]));
  }
  return note;
}
