import { splitMemoPages } from '@/lib/research/memo-pages';

export type ReadingSection = { titulo: string; parrafos: string[] };

type ReadingThesis = {
  narrative_sections?: ReadingSection[] | null;
  thesis_markdown?: string | null;
  executive_summary?: string | null;
  hypothesis?: string | null;
};

const normalize = (text: string) =>
  text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim().toLowerCase();

/** Párrafos legibles de un cuerpo markdown: sin encabezados, viñetas ni énfasis. */
function markdownParagraphs(body: string): string[] {
  const paragraphs: string[] = [];
  for (const block of body.split(/\n\s*\n/)) {
    let prose: string[] = [];
    const flush = () => {
      if (prose.length) paragraphs.push(prose.join(' '));
      prose = [];
    };
    for (const raw of block.split('\n')) {
      const line = raw.trim();
      if (!line || /^#{1,6}\s/.test(line) || /^[-*_]{3,}$/.test(line) || /^\|/.test(line)) {
        flush();
        continue;
      }
      const bullet = /^(?:[-*+]|\d+[.)])\s+(.*)$/.exec(line);
      const text = (bullet ? bullet[1] : line).replace(/\*\*|__|`/g, '').trim();
      if (!text) continue;
      if (bullet) {
        flush();
        paragraphs.push(text);
      } else {
        prose.push(text);
      }
    }
    flush();
  }
  return paragraphs;
}

/**
 * Secciones de la lectura editorial de una tesis. Las versiones actuales traen
 * `narrative_sections`; una tesis antigua solo tiene `thesis_markdown` y la
 * lectura salía sin catalizadores ni riesgos (el texto solo estaba en la
 * descarga Markdown; auditoría A10). Sin secciones, se derivan de los `## ` del
 * memo. Se omiten las que ya pinta la página aparte (resumen, hipótesis) y las
 * tablas markdown, que en prosa serían ilegibles (siguen en la descarga).
 */
export function readingSections(thesis: ReadingThesis): ReadingSection[] {
  if (thesis.narrative_sections && thesis.narrative_sections.length > 0) return thesis.narrative_sections;
  const markdown = thesis.thesis_markdown?.trim();
  if (!markdown) return [];
  const shownApart = new Set<string>();
  if (thesis.executive_summary?.trim()) shownApart.add('resumen ejecutivo');
  if (thesis.hypothesis?.trim()) shownApart.add('hipotesis');
  return splitMemoPages(markdown)
    .filter((page) => !shownApart.has(normalize(page.title)))
    .map((page) => ({ titulo: page.title, parrafos: markdownParagraphs(page.body) }))
    .filter((section) => section.parrafos.length > 0);
}
