import { readFileSync } from 'node:fs';
import path from 'node:path';

import PDFDocument from 'pdfkit';

/**
 * PDF de lectura de la tesis a partir del memo Markdown canonico del backend
 * (misma fuente que la descarga .md: nada se inventa en el render).
 * Tipografia de marca (Instrument Serif, OFL) para titulos y Helvetica para
 * el cuerpo. Sin proveedores externos: pdfkit corre en el route handler.
 */

const FONT_DIR = path.join(process.cwd(), 'app', 'fonts');
const DISPLAY = readFileSync(path.join(FONT_DIR, 'InstrumentSerif-Regular.ttf'));
const DISPLAY_ITALIC = readFileSync(path.join(FONT_DIR, 'InstrumentSerif-Italic.ttf'));

const INK = '#111827';
const MUTED = '#6b7280';
const ACCENT = '#0f766e';
const RULE = '#d1d5db';

/**
 * Sin ligaduras OpenType en la tipografía de marca: la ligadura «fi» se
 * incrustaba como un único glifo y al copiar texto del PDF varios visores
 * lo soltaban («financiero» -> «fnanciero» en el pie). Helvetica (base 14)
 * no liga, así que solo se desactiva en los textos con Display.
 */
const SIN_LIGADURAS = {
  // pdfkit/fontkit acepta en runtime el objeto {etiqueta: boolean}; el tipado
  // publicado solo declara la forma array y no exporta su tipo, de ahí el cast.
  features: { liga: false } as unknown as never[],
} as const;

type InlineToken = { text: string; bold?: boolean; italic?: boolean };

/** Inline minimo del memo: **negrita**, _cursiva_, [texto](url). */
function parseInline(input: string): InlineToken[] {
  const tokens: InlineToken[] = [];
  const pattern = /(\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\)|(?<![\p{L}\p{N}_])_[^_\n]+_(?![\p{L}\p{N}_])|`[^`]+`)/gu;
  let last = 0;
  for (const match of input.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > last) tokens.push({ text: input.slice(last, index) });
    const raw = match[0];
    if (raw.startsWith('**')) {
      tokens.push({ text: raw.slice(2, -2), bold: true });
    } else if (raw.startsWith('[')) {
      const label = raw.slice(1, raw.indexOf(']'));
      const url = raw.slice(raw.indexOf('](') + 2, -1);
      tokens.push({ text: `${label} (${url})` });
    } else if (raw.startsWith('`')) {
      tokens.push({ text: raw.slice(1, -1) });
    } else {
      tokens.push({ text: raw.slice(1, -1), italic: true });
    }
    last = index + raw.length;
  }
  if (last < input.length) tokens.push({ text: input.slice(last) });
  return tokens;
}

function writeInline(doc: PDFKit.PDFDocument, tokens: InlineToken[], size: number, color: string) {
  tokens.forEach((token, index) => {
    doc
      .font(token.bold ? 'Helvetica-Bold' : token.italic ? 'Helvetica-Oblique' : 'Helvetica')
      .fontSize(size)
      .fillColor(token.italic ? MUTED : color)
      .text(token.text, { continued: index < tokens.length - 1, lineGap: 3 });
  });
}

function tableRow(
  doc: PDFKit.PDFDocument,
  cells: string[],
  widths: number[],
  x: number,
  bold: boolean,
) {
  // Altura de la fila entera antes de pintar: si no cabe, salto de pagina
  // antes de la primera celda (si no, cada celda saltaba de pagina sola).
  doc.font(bold ? 'Helvetica-Bold' : 'Helvetica').fontSize(9.5);
  const rowHeight = Math.max(
    ...cells.map((cell, i) => doc.heightOfString(cell, { width: widths[i] - 8 })),
  );
  const bottom = doc.page.height - doc.page.margins.bottom;
  if (doc.y + rowHeight > bottom) doc.addPage();
  const y = doc.y;
  let maxHeight = 0;
  cells.forEach((cell, i) => {
    doc
      .font(bold ? 'Helvetica-Bold' : 'Helvetica')
      .fontSize(9.5)
      .fillColor(INK);
    const height = doc.heightOfString(cell, { width: widths[i] - 8 });
    doc.text(cell, x + widths.slice(0, i).reduce((a, b) => a + b, 0), y, { width: widths[i] - 8 });
    maxHeight = Math.max(maxHeight, height);
  });
  doc.y = y + maxHeight + 6;
  doc.x = x;
}

/** Anchos por contenido: cada columna recibe como mínimo lo que ocupa su
 *  palabra más larga (nunca parte «derivado»), el resto se reparte según el
 *  largo del texto. El texto no se recorta. */
function columnWidths(rows: string[][], total: number): number[] {
  const count = rows[0]?.length ?? 1;
  const cols = Array.from({ length: count }, (_, c) => rows.map((r) => r[c] ?? ''));
  const minW = cols.map((cells) => {
    const longest = Math.max(
      4,
      ...cells.flatMap((cell) => cell.split(/\s+/).map((word) => word.length)),
    );
    return Math.min(longest * 5.6 + 12, total * 0.3);
  });
  const weight = cols.map((cells) => Math.min(60, Math.max(6, ...cells.map((cell) => cell.length))));
  const free = Math.max(0, total - minW.reduce((a, b) => a + b, 0));
  const wSum = weight.reduce((a, b) => a + b, 0);
  const widths = minW.map((m, i) => m + (weight[i] / wSum) * free);
  const sum = widths.reduce((a, b) => a + b, 0);
  return widths.map((w) => (w / sum) * total);
}

/** Convierte el memo Markdown de la tesis en un PDF listo para descargar. */
export async function buildMemoPdf(markdown: string): Promise<Buffer> {
  const doc = new PDFDocument({
    size: 'A4',
    // bufferPages: el pie (marca + numero) se escribe al final en todas.
    bufferPages: true,
    margins: { top: 56, bottom: 56, left: 56, right: 56 },
    info: { Title: markdown.split('\n')[0]?.replace(/^#\s*/, '') ?? 'Tesis' },
  });
  const chunks: Buffer[] = [];
  const done = new Promise<Buffer>((resolve, reject) => {
    doc.on('data', (chunk: Buffer) => chunks.push(chunk));
    doc.on('end', () => resolve(Buffer.concat(chunks)));
    doc.on('error', reject);
  });
  doc.registerFont('Display', DISPLAY);
  doc.registerFont('DisplayItalic', DISPLAY_ITALIC);

  const contentWidth = doc.page.width - 112;
  const left = doc.page.margins.left;

  const lines = markdown.split('\n');
  let i = 0;
  while (i < lines.length) {
    const line = lines[i].trimEnd();
    if (line.startsWith('|')) {
      // Tabla GFM: se acumulan las filas y la cabecera es la fila anterior
      // al separador |---| (nunca se confunde con una fila de datos).
      const rows: string[][] = [];
      let separatorIndex = -1;
      while (i < lines.length && lines[i].trimEnd().startsWith('|')) {
        const cells = lines[i].trimEnd().split('|').slice(1, -1).map((cell) => cell.trim());
        if (cells.every((cell) => /^:?-{2,}:?$/.test(cell))) {
          separatorIndex = rows.length;
        } else {
          rows.push(cells);
        }
        i += 1;
      }
      const header = separatorIndex >= 0 && rows.length > 0 ? rows[0] : null;
      const body = header ? rows.slice(1) : rows;
      if (header) {
        const widths = columnWidths(rows, contentWidth);
        tableRow(doc, header, widths, left, true);
        doc.moveTo(left, doc.y - 3).lineTo(left + contentWidth, doc.y - 3).lineWidth(0.5).strokeColor(RULE).stroke();
        for (const row of body) tableRow(doc, row, widths, left, false);
      } else {
        for (const row of body) {
          const widths = row.map(() => contentWidth / row.length);
          tableRow(doc, row, widths, left, false);
        }
      }
      doc.moveDown(0.3);
      continue;
    }
    if (line.startsWith('# ')) {
      doc.moveDown(0.4);
      doc.font('Display').fontSize(22).fillColor(INK).text(line.slice(2), { lineGap: 2, ...SIN_LIGADURAS });
      doc.moveDown(0.2);
      doc.moveTo(left, doc.y).lineTo(left + contentWidth, doc.y).lineWidth(0.75).strokeColor(ACCENT).stroke();
      doc.moveDown(0.5);
    } else if (line.startsWith('## ')) {
      doc.moveDown(0.8);
      doc.font('Display').fontSize(16).fillColor(ACCENT).text(line.slice(3), { lineGap: 2, ...SIN_LIGADURAS });
      doc.moveDown(0.25);
    } else if (line.startsWith('### ')) {
      doc.moveDown(0.5);
      doc.font('Helvetica-Bold').fontSize(11).fillColor(INK).text(line.slice(4), { lineGap: 2 });
      doc.moveDown(0.15);
    } else if (line.startsWith('- ')) {
      doc.font('Helvetica').fontSize(10).fillColor(INK).text('\u2022  ', { continued: true, indent: 12 });
      writeInline(doc, parseInline(line.slice(2)), 10, INK);
      doc.moveDown(0.12);
    } else if (line.startsWith('> ')) {
      doc.moveDown(0.2);
      doc.font('Helvetica-Oblique').fontSize(10).fillColor('#92400e').text(line.slice(2), { indent: 8, lineGap: 2 });
      doc.moveDown(0.2);
    } else if (line === '---') {
      doc.moveDown(0.6);
      doc.moveTo(left, doc.y).lineTo(left + contentWidth, doc.y).lineWidth(0.5).strokeColor(RULE).stroke();
      doc.moveDown(0.6);
    } else if (line.trim() !== '') {
      writeInline(doc, parseInline(line), 10, INK);
    } else {
      doc.moveDown(0.35);
    }
    i += 1;
  }

  // Pie de cada pagina: marca + pagina, discreto.
  const range = doc.bufferedPageRange();
  for (let i = range.start; i < range.start + range.count; i += 1) {
    doc.switchToPage(i);
    // El pie vive bajo el margen inferior: se anula al escribir para que
    // pdfkit no lo empuje a una pagina nueva.
    const bottomMargin = doc.page.margins.bottom;
    doc.page.margins.bottom = 0;
    const bottom = doc.page.height - 40;
    doc.font('DisplayItalic').fontSize(9).fillColor(MUTED).text('GerarAI — documento informativo, no es asesoramiento financiero', 56, bottom, {
      width: contentWidth, align: 'left', lineBreak: false, ...SIN_LIGADURAS,
    });
    doc.font('Helvetica').fontSize(9).fillColor(MUTED).text(`${i + 1} / ${range.start + range.count}`, 56, bottom, {
      width: contentWidth, align: 'right', lineBreak: false,
    });
    doc.page.margins.bottom = bottomMargin;
  }

  doc.end();
  return done;
}
