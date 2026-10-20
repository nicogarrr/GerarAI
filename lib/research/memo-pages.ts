// Sin 'use client': lo importan el servidor (ThesisMemo) y el paginador cliente.

export type MemoPage = { id: string; title: string; body: string };

/** Parte el memorando por sus encabezados `## `; el texto previo (título)
 *  se une a la primera sección. */
export function splitMemoPages(markdown: string): MemoPage[] {
  const pages: MemoPage[] = [];
  let preface: string[] = [];
  let current: { title: string; lines: string[] } | null = null;
  const flush = () => {
    if (!current) return;
    pages.push({ id: `p${pages.length}`, title: current.title, body: current.lines.join('\n').trim() });
  };
  for (const line of markdown.split('\n')) {
    const heading = /^##\s+(.+?)\s*$/.exec(line);
    if (heading) {
      flush();
      // El paginador numera las opciones ({i + 1}.): si el propio encabezado
      // ya trae numeracion ("## 1. Resumen ejecutivo") se duplicaba ("1. 1.").
      // Se conserva en el cuerpo (lines), solo se limpia el titulo del selector.
      // Exige separador + espacio: "1.5 Dividendos" no es una enumeracion.
      const title = heading[1].replace(/[*_`]/g, '').replace(/^\d+[.\-)]\s+/, '');
      current = { title, lines: [...preface.filter((l) => !/^#\s/.test(l)), line] };
      preface = [];
    } else if (current) {
      current.lines.push(line);
    } else {
      preface.push(line);
    }
  }
  flush();
  return pages.filter((page) => page.body.replace(/^##.*$/m, '').trim().length > 0);
}
