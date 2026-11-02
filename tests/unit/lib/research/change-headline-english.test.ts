import { describe, expect, it } from 'vitest';
import { changeHeadlineCopy } from '@/lib/research/change-copy';

const GDELT_ES = 'Revisa la fuente; la fecha de GDELT no es la fecha de publicación y el titular no confirma por sí solo los hechos.';
const GDELT_EN = 'Check the source; the GDELT date is not the publication date and the headline alone does not confirm the facts.';
const HEAD_ES = 'Revisa la fuente; el titular no confirma por sí solo los hechos.';
const HEAD_EN = 'Check the source; the headline alone does not confirm the facts.';
const WATCH_ES = 'Señal de vigilancia: si SpaceX cierra acuerdos con operadoras grandes, el argumento de que el foso de AST son sus acuerdos con operadoras se debilita.';
const WATCH_EN = "Watch signal: if SpaceX closes deals with large carriers, the argument that AST's moat is its carrier agreements weakens.";

describe('«Qué ha cambiado» en inglés: aviso de la noticia sin castellano', () => {
  it('traduce el aviso guardado en castellano (GDELT y titular) con inglés', () => {
    expect(changeHeadlineCopy(`Artículo de Yahoo Finance, fechada el 2026-10-29 por Yahoo Finance: Apple releases results. ${GDELT_ES}`, 'en'))
      .toEqual({ text: 'Apple releases results.', note: GDELT_EN });
    expect(changeHeadlineCopy(`Artículo de Reuters, detectado por GDELT el 2026-10-29: SpaceX signs deal. ${WATCH_ES} ${HEAD_ES}`, 'en'))
      .toEqual({ text: `SpaceX signs deal. ${WATCH_EN}`, note: HEAD_EN });
  });

  it('un aviso guardado en inglés también separa el envoltorio y el aviso', () => {
    expect(changeHeadlineCopy(`Article from Yahoo Finance, dated 2026-10-29 by Yahoo Finance: Apple releases results. ${GDELT_EN}`, 'en'))
      .toEqual({ text: 'Apple releases results.', note: GDELT_EN });
    expect(changeHeadlineCopy(`Article from Reuters, detected by GDELT on 2026-10-29: SpaceX signs deal. ${WATCH_EN} ${HEAD_EN}`, 'en'))
      .toEqual({ text: `SpaceX signs deal. ${WATCH_EN}`, note: HEAD_EN });
  });

  it('en castellano (por defecto) un aviso guardado en inglés sale en castellano', () => {
    expect(changeHeadlineCopy(`Article from Yahoo Finance, dated 2026-10-29 by Yahoo Finance: Apple releases results. ${GDELT_EN}`))
      .toEqual({ text: 'Apple releases results.', note: GDELT_ES });
    expect(changeHeadlineCopy(`Artículo de Reuters, detectado por GDELT el 2026-10-29: SpaceX signs deal. ${WATCH_ES} ${HEAD_ES}`))
      .toEqual({ text: `SpaceX signs deal. ${WATCH_ES}`, note: HEAD_ES });
  });

  it('los textos que compara son los que escribe el backend', async () => {
    const { readFileSync } = await import('node:fs');
    const squash = (s: string) => s.replace(/"\s*\n\s*"/g, '');
    const news = squash(readFileSync('data-engine/app/services/tracked_news_alerts.py', 'utf8'));
    const asts = squash(readFileSync('data-engine/app/services/asts_spacex_signal.py', 'utf8'));
    for (const s of [GDELT_ES, GDELT_EN]) expect(news).toContain(s);
    for (const s of [HEAD_ES, HEAD_EN, WATCH_ES, WATCH_EN]) expect(asts).toContain(s);
  });
});
