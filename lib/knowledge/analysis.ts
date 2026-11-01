// Vista del modo "Análisis" del chat de la biblioteca. Sin imports en runtime: se prueba con node --test.

import type { TranslateFn } from '../i18n/translate.ts';

export type AnalysisCitation = {
  chunk_id: number; document_id: number; title: string; author: string | null;
  page_number: number | null; chunk_index: number; quote: string;
  source_url: string | null; publication_date: string | null; document_type: string;
};
export type CitedPoint = { text: string; nombre?: string; citation: AnalysisCitation };
export type LibraryAnalysis = {
  tesis: CitedPoint[];
  error: CitedPoint;
  escenarios: { nombre: string; probabilidad: number; disparador: string }[];
  modelos: CitedPoint[];
  no_se: string[];
  probabilidades: string;
  aviso: string;
};

export const SUGGESTED_QUESTIONS = [
  '¿Cuándo tiene sentido recomprar acciones?',
  '¿Qué es el margen de seguridad?',
  '¿Cómo piensa Munger sobre la inversión de problemas (invertir al revés)?',
  '¿Qué dicen las cartas sobre los fosos competitivos?',
] as const;

/** Rótulos del texto copiable; el panel los pasa en el idioma elegido (brain.library.*). */
export type AnalysisLabels = {
  thesis: string; wrong: string; scenarios: string; models: string; unknown: string;
  unregisteredAuthor: string; unregisteredPage: string;
  page: (n: number) => string;
  scenario: (name: string, probability: number, trigger: string) => string;
};

const ES_LABELS: AnalysisLabels = {
  thesis: 'Tesis', wrong: 'Qué me haría equivocarme', scenarios: 'Escenarios', models: 'Modelos mentales', unknown: 'Lo que no sé',
  unregisteredAuthor: 'Autor no registrado', unregisteredPage: 'página no registrada',
  page: (n) => `p. ${n}`,
  scenario: (name, probability, trigger) => `${name}: ${probability} %. Disparador: ${trigger}`,
};

/** Rótulos en el idioma del traductor (brain.library.*). */
export function analysisLabels(t: TranslateFn): AnalysisLabels {
  return {
    thesis: t('brain.library.thesis'),
    wrong: t('brain.library.whatWouldProveMeWrong'),
    scenarios: t('brain.library.scenarios'),
    models: t('brain.library.mentalModels'),
    unknown: t('brain.library.whatIDontKnow'),
    unregisteredAuthor: t('brain.library.unregisteredAuthor'),
    unregisteredPage: t('brain.library.unregisteredPage'),
    page: (n) => t('brain.library.pageShort', { n }),
    scenario: (name, probability, trigger) => t('brain.library.scenarioLine', { name, probability, trigger }),
  };
}

function source(c: AnalysisCitation, l: AnalysisLabels): string {
  return `${c.author ?? l.unregisteredAuthor} · ${c.title} · ${c.page_number === null ? l.unregisteredPage : l.page(c.page_number)}`;
}

/** Texto plano del análisis para copiar: mismas secciones, citas con su origen y el aviso. */
export function analysisToText(a: LibraryAnalysis, l: AnalysisLabels = ES_LABELS): string {
  const cited = (p: CitedPoint) => `${p.nombre ? `${p.nombre}: ` : ''}${p.text}\n   «${p.citation.quote}» (${source(p.citation, l)})`;
  return [
    l.thesis,
    ...a.tesis.map((p, i) => `${i + 1}. ${cited(p)}`),
    '',
    l.wrong,
    cited(a.error),
    '',
    `${l.scenarios} (${a.probabilidades})`,
    ...a.escenarios.map(s => `- ${l.scenario(s.nombre, s.probabilidad, s.disparador)}`),
    '',
    l.models,
    ...a.modelos.map(p => `- ${cited(p)}`),
    '',
    l.unknown,
    ...a.no_se.map(t => `- ${t}`),
    '',
    a.aviso,
  ].join('\n');
}

/** Ctrl+Enter o Cmd+Enter envían; Enter solo no. */
export function isSubmitShortcut(e: { key: string; ctrlKey: boolean; metaKey: boolean }): boolean {
  return e.key === 'Enter' && (e.ctrlKey || e.metaKey);
}
