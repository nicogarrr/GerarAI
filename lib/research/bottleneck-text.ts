/**
 * Cuellos de botella (routes/bottlenecks.py y bottleneck_discovery_service.py):
 * el backend manda en castellano el método, la limitación, la nota de los
 * candidatos, la etiqueta «INFERIDO» y la hipótesis de cada candidato (una
 * plantilla con listas cerradas). En inglés se traducen; en castellano, y con
 * un texto que no se reconoce, pasa el del backend tal cual.
 */
import { naFor } from '@/lib/format';
import type { Locale } from '@/lib/i18n/locale';

const FIXED_EN: Record<string, string> = {
  'Extracción determinista de documentos y titulares almacenados': 'Deterministic extraction from stored documents and headlines',
  'Se requieren al menos dos autores o editores independientes; no implica una recomendación de inversión':
    'At least two independent authors or publishers are required; this is not an investment recommendation',
  'Candidatos INFERIDOS por un modelo a partir de evidencias almacenadas; son hipótesis, no hechos ni recomendaciones. Las URLs proceden de la fuente guardada, nunca del modelo':
    'Candidates INFERRED by a model from stored evidence; they are hypotheses, not facts or recommendations. URLs come from the stored source, never from the model',
  INFERIDO: 'INFERRED',
};

const EXPOSURES_EN: Record<string, string> = { beneficiada: 'helped', afectada: 'hurt' };

const CHANNELS_EN: Record<string, string> = {
  'suministra de forma directa el recurso o componente escaso': 'it directly supplies the scarce resource or component',
  'controla capacidad productiva en el segmento afectado': 'it controls production capacity in the affected segment',
  'depende del recurso escaso para producir o entregar': 'it depends on the scarce resource to produce or deliver',
  'opera infraestructura o logística ligada al cuello de botella': 'it runs infrastructure or logistics tied to the bottleneck',
  'ofrece una alternativa al recurso escaso': 'it offers an alternative to the scarce resource',
};

const UNIDENTIFIED_ES = 'Una empresa aún sin identificar (N/D)';
const UNIDENTIFIED_EN = `A company not yet identified (${naFor('en')})`;

const REASONING =
  /^Hipótesis del modelo, no un hecho: (.+) podría resultar (\S+) por este cuello de botella porque (.+)\. Se infiere de las evidencias citadas\.$/;

export function bottleneckText<T extends string | null | undefined>(text: T, locale: Locale): T | string {
  if (locale !== 'en' || !text) return text;
  return Object.hasOwn(FIXED_EN, text) ? FIXED_EN[text] : text;
}

/** La hipótesis de un candidato; si no encaja con la plantilla actual, pasa tal cual. */
export function bottleneckReasoningText(text: string, locale: Locale): string {
  if (locale !== 'en' || !text) return text;
  const match = REASONING.exec(text.trim());
  if (!match) return text;
  const [, who, exposure, channel] = match;
  if (!Object.hasOwn(EXPOSURES_EN, exposure) || !Object.hasOwn(CHANNELS_EN, channel)) return text;
  const subject = who === UNIDENTIFIED_ES ? UNIDENTIFIED_EN : who;
  return `Model hypothesis, not a fact: ${subject} could be ${EXPOSURES_EN[exposure]} by this bottleneck because ${CHANNELS_EN[channel]}. Inferred from the cited evidence.`;
}
