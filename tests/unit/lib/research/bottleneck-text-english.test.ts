import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { bottleneckReasoningText, bottleneckText } from '@/lib/research/bottleneck-text';

const squash = (s: string) => s.replace(/"\s*\n\s*"/g, '');
const ROUTES = squash(readFileSync('data-engine/app/api/routes/bottlenecks.py', 'utf8'));
const SERVICE = readFileSync('data-engine/app/services/bottleneck_discovery_service.py', 'utf8');
const PAGE = readFileSync('app/(root)/cuellos/page.tsx', 'utf8');
const SPANISH = /[áéíóúñ¿¡]|\b(?:de|del|los|las|por|una|para|hipótesis|que)\b/i;

function pyDict(name: string): Record<string, string> {
  const block = SERVICE.slice(SERVICE.indexOf(`${name} = {`));
  const body = block.slice(0, block.indexOf('}'));
  return Object.fromEntries([...body.matchAll(/"([^"]+)":\s*"([^"]+)"/g)].map((m) => [m[1], m[2]]));
}

describe('Cuellos de botella en inglés: textos del backend sin castellano', () => {
  it('método, limitación, nota y etiqueta salen en inglés', () => {
    const fixed = [
      ROUTES.match(/method: str = "([^"]+)"/)![1],
      ROUTES.match(/limitation: str = "([^"]+)"/)![1],
      ROUTES.match(/note: str = \(\s*"([^)]+)"\s*\)/)![1],
      'INFERIDO',
    ];
    for (const text of fixed) {
      const en = bottleneckText(text, 'en');
      expect(en, text).not.toBe(text);
      expect(en, text).not.toMatch(SPANISH);
      expect(bottleneckText(text, 'es')).toBe(text);
    }
  });

  it('cada hipótesis de la plantilla (exposición × canal) sale en inglés', () => {
    const exposures = Object.values(pyDict('EXPOSURES'));
    const channels = Object.values(pyDict('CHANNELS'));
    expect(exposures.length).toBe(2);
    expect(channels.length).toBe(5);
    const tmpl = SERVICE.match(/f"(Hipótesis del modelo[^"]*)"\s*f"([^"]*)"/)!;
    const template = tmpl[1] + tmpl[2];
    for (const who of ['NVDA (NVIDIA · Semiconductors)', 'Una empresa aún sin identificar (N/D)']) {
      for (const exposure of exposures) {
        for (const channel of channels) {
          const text = template.replace('{who}', who).replace('{EXPOSURES[exposure]}', exposure).replace('{CHANNELS[channel]}', channel);
          const en = bottleneckReasoningText(text, 'en');
          expect(en, text).toMatch(/^Model hypothesis, not a fact: /);
          expect(en.replace(who, ''), text).not.toMatch(SPANISH);
          expect(bottleneckReasoningText(text, 'es')).toBe(text);
        }
      }
    }
    expect(bottleneckReasoningText('Hipótesis del modelo, no un hecho: Una empresa aún sin identificar (N/D) podría resultar afectada por este cuello de botella porque ofrece una alternativa al recurso escaso. Se infiere de las evidencias citadas.', 'en'))
      .toBe('Model hypothesis, not a fact: A company not yet identified (N/A) could be hurt by this bottleneck because it offers an alternative to the scarce resource. Inferred from the cited evidence.');
  });

  it('un texto antiguo o desconocido pasa tal cual', () => {
    expect(bottleneckReasoningText('Texto libre antiguo.', 'en')).toBe('Texto libre antiguo.');
    expect(bottleneckText('Otro texto', 'en')).toBe('Otro texto');
  });

  it('la página usa los traductores y el nombre del tema traducido en cada candidato', () => {
    expect(PAGE).toContain('bottleneckReasoningText(item.reasoning');
    expect(PAGE).toContain('bottleneckText(item.label');
    expect(PAGE).toContain('bottleneckText(bottlenecks.method');
    expect(PAGE).toContain('bottleneckText(bottlenecks.limitation');
    expect(PAGE).toContain('bottleneckText(discoveries.note');
    expect(PAGE).toContain('bottleneckThemeName(item.theme, t)');
  });
});
