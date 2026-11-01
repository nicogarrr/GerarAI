import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

// prefers-reduced-motion: las animaciones en bucle de Tailwind (pulse en
// esqueletos, spin en spinners, bounce, ping) deben detenerse, y el
// autoscroll suave del chat del Cerebro debe saltar de golpe.
// WCAG 2.2 SC 2.2.2 y SC 2.3.3.
test('a11y: el bloque prefers-reduced-motion detiene las utilidades animate-*', () => {
  const css = readFileSync('app/globals.css', 'utf8');
  const block = css.match(/@media \(prefers-reduced-motion: reduce\) \{([\s\S]*?)\n\}/);
  assert.ok(block, 'no existe el bloque @media (prefers-reduced-motion: reduce)');
  for (const util of ['.animate-pulse', '.animate-spin', '.animate-bounce', '.animate-ping']) {
    assert.ok(
      block[1].includes(util),
      `el bloque reduced-motion no detiene ${util} (esqueletos/spinners siguen animándose)`,
    );
  }
});

test('a11y: el autoscroll del Cerebro respeta prefers-reduced-motion', () => {
  const src = readFileSync('components/brain/GlobalBrainPanel.tsx', 'utf8');
  assert.ok(
    src.includes("matchMedia('(prefers-reduced-motion: reduce)')"),
    'el scrollTo del chat no consulta prefers-reduced-motion',
  );
});
