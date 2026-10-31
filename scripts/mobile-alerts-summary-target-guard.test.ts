import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

// Los <summary> "Ver análisis original" de alertas activadas (AlertsManager)
// y "Aviso original" de inicio (PersonalizedOverview) son controles táctiles:
// en móvil deben reservar 44px reales (WCAG 2.5.5) y pueden volver a 40px en
// escritorio. SIN display:flex/inline-flex: eso elimina el marcador nativo de
// despliegue del <summary>.
const FILES = [
  'components/alerts/AlertsManager.tsx',
  'components/PersonalizedOverview.tsx',
];

for (const file of FILES) {
  test(`guard móvil: summary táctil 44px con marcador nativo (${file})`, () => {
    const source = readFileSync(file, 'utf8');
    const summaries = [...source.matchAll(/<summary\s+className="([^"]*min-h-1[01][^"]*)"/g)];
    assert.ok(summaries.length > 0, `no se encontró el <summary> con min-h-1x en ${file}`);
    for (const m of summaries) {
      const classes = m[1];
      assert.ok(
        /\bmin-h-11\b/.test(classes) && /\bsm:min-h-10\b/.test(classes),
        `<summary> sin min-h-11 móvil + sm:min-h-10 en ${file}: ${classes}`,
      );
      assert.ok(
        !/(^|\s)(inline-)?flex(\s|$)/.test(classes),
        `<summary> con display flex pierde el marcador nativo en ${file}: ${classes}`,
      );
    }
  });
}
