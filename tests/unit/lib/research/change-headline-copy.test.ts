import { describe, expect, it } from 'vitest';
import { changeHeadlineCopy } from '@/lib/research/change-copy';
describe('clean persisted news wrappers', () => {
  it.each(['fechada el 2026-10-29 por Yahoo Finance','fechado el 2026-10-29 por la fuente','detectada por GDELT el 2026-10-29','detectado por GDELT el 2026-10-29'])('strips generated attribution %s but keeps truth notice separate', (date) => {
    const copy=changeHeadlineCopy(`Artículo de Yahoo Finance, ${date}: Apple releases results. Revisa la fuente; la fecha de GDELT no es la fecha de publicación y el titular no confirma por sí solo los hechos.`);
    expect(copy.text).toBe('Apple releases results.');
    expect(copy.note).toContain('no es la fecha de publicación');
    expect(copy.note).toContain('el titular no confirma');
  });
  it('removes review boilerplate but preserves hypothesis and publisher headline dates', () => {
    expect(changeHeadlineCopy('Noticia material que requiere revisión de la tesis: ASTS Could Grow in 2027').text).toBe('ASTS Could Grow in 2027');
    expect(changeHeadlineCopy('Apple: 2026-10-29 outlook may change')).toEqual({text:'Apple: 2026-10-29 outlook may change',note:null});
  });
});
